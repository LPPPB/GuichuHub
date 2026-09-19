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
    # Historic 0001 data may contain unbounded duplicate BVID history.  The
    # explicit, resumable calendar_identity_backfill job must reconcile it
    # before this schema-only revision changes the primary key.
    duplicates_remain = op.get_bind().execute(sa.text("""
        SELECT EXISTS (
            SELECT 1 FROM app.calendar_videos GROUP BY bvid HAVING count(*) > 1
        )
    """)).scalar_one()
    if duplicates_remain:
        raise RuntimeError(
            "calendar identity backfill must complete before upgrading to 0002"
        )
    op.drop_constraint("calendar_videos_pkey", "calendar_videos", schema="app", type_="primary")
    op.create_primary_key("calendar_videos_pkey", "calendar_videos", ["bvid"], schema="app")


def downgrade():
    # Reinstating terminal-state uniqueness can discard request history.
    raise RuntimeError("This data-preserving revision requires forward repair or a verified backup restore")
