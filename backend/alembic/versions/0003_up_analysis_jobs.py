"""Durable, fenced UP analysis jobs without expanding API collection grants."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0003_up_analysis_jobs"
down_revision = "0002_recovery_and_identity"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "up_analysis_jobs",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("requested_by", sa.Text(), nullable=False),
        sa.Column("roster", JSONB(), nullable=False),
        sa.Column("progress", JSONB(), nullable=False, server_default="{}"),
        sa.Column("result_summary", JSONB(), nullable=False, server_default="{}"),
        sa.Column("error", JSONB()),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("started_at", sa.BigInteger()),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.Column("finished_at", sa.BigInteger()),
        sa.Column("worker_id", sa.String(128)),
        sa.Column("lease_until", sa.BigInteger()),
        sa.Column("fencing_token", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("batch_ts", sa.BigInteger()),
        sa.CheckConstraint("status IN ('queued','running','finalizing','succeeded','partial','failed')", name="ck_up_analysis_status"),
        schema="app",
    )
    op.create_index("uq_up_analysis_active", "up_analysis_jobs", [sa.text("(1)")],
                    unique=True, schema="app",
                    postgresql_where=sa.text("status IN ('queued','running','finalizing')"))
    op.execute("""
    DO $$ BEGIN
        IF EXISTS (SELECT FROM pg_roles WHERE rolname='kichu_api') THEN
            GRANT SELECT, INSERT ON app.up_analysis_jobs TO kichu_api;
        END IF;
        IF EXISTS (SELECT FROM pg_roles WHERE rolname='kichu_worker') THEN
            GRANT SELECT, INSERT, UPDATE ON app.up_analysis_jobs TO kichu_worker;
        END IF;
        IF EXISTS (SELECT FROM pg_roles WHERE rolname='kichu_backup') THEN
            GRANT SELECT ON app.up_analysis_jobs TO kichu_backup;
        END IF;
    END $$;
    """)


def downgrade():
    op.drop_table("up_analysis_jobs", schema="app")
