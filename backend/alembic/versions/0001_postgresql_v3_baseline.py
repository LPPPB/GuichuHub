"""PostgreSQL baseline replacing V3 SQLite schema versions 1 through 11."""

from alembic import op

from pathlib import Path

revision = "0001_postgresql_v3_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE SCHEMA IF NOT EXISTS app")
    op.execute("CREATE SCHEMA IF NOT EXISTS auth")
    op.execute(Path(__file__).with_name("0001_baseline.sql").read_text(encoding="utf-8"))


def downgrade():
    op.execute("DROP SCHEMA auth CASCADE")
    op.execute("DROP SCHEMA app CASCADE")
