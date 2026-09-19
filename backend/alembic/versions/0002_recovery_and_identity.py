"""Canonical calendar videos, active request uniqueness and fenced backfills."""

from alembic import op
import sqlalchemy as sa

revision = "0002_recovery_and_identity"
down_revision = "0001_postgresql_v3_baseline"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("uq_tracking_request_state", "tracking_requests", schema="app", type_="unique")
    op.create_index("uq_tracking_request_active", "tracking_requests", ["mid", "visitor_id"],
                    schema="app", unique=True, postgresql_where=sa.text("status = 'pending'"))
    op.add_column("backfill_progress", sa.Column("claim_owner", sa.String(128)), schema="app")
    op.add_column("backfill_progress", sa.Column("lease_until", sa.BigInteger()), schema="app")
    op.add_column("backfill_progress", sa.Column("fencing_token", sa.BigInteger(), nullable=False, server_default="0"), schema="app")
    # Preserve every author before consolidating historical duplicates.
    op.execute("""INSERT INTO app.calendar_video_authors(bvid,mid,last_seen_at,missing_count,status)
        SELECT bvid,mid,last_seen_at,missing_count,status FROM app.calendar_videos
        ON CONFLICT(bvid,mid) DO NOTHING""")
    op.execute("""WITH best AS (
        SELECT DISTINCT ON(bvid) * FROM app.calendar_videos
        ORDER BY bvid, views DESC, fetched_at DESC, mid
    ) UPDATE app.calendar_videos v SET views=b.views, pub_date=b.pub_date,
        pub_date_str=b.pub_date_str, title=b.title, fetched_at=b.fetched_at
        FROM best b WHERE v.bvid=b.bvid""")
    op.execute("""DELETE FROM app.calendar_videos v USING app.calendar_videos keep
        WHERE v.bvid=keep.bvid AND v.mid>keep.mid""")
    op.drop_constraint("calendar_videos_pkey", "calendar_videos", schema="app", type_="primary")
    op.create_primary_key("calendar_videos_pkey", "calendar_videos", ["bvid"], schema="app")


def downgrade():
    # Reinstating terminal-state uniqueness can discard request history.
    raise RuntimeError("This data-preserving revision requires forward repair or a verified backup restore")
