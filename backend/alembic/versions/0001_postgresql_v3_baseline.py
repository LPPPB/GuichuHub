"""PostgreSQL baseline replacing V3 SQLite schema versions 1 through 11."""

from alembic import op

from storage.models import Base

revision = "0001_postgresql_v3_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    op.execute("CREATE SCHEMA IF NOT EXISTS app")
    op.execute("CREATE SCHEMA IF NOT EXISTS auth")
    Base.metadata.create_all(bind=bind)


def downgrade():
    op.execute("DROP SCHEMA auth CASCADE")
    op.execute("DROP SCHEMA app CASCADE")
