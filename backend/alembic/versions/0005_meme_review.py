"""Review-only immutable evidence and publication documents."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0005_meme_review'
down_revision = '0004_radar_v2'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('meme_review_state',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('revision', sa.BigInteger(), nullable=False),
        sa.Column('payload', JSONB(), nullable=False),
        sa.Column('updated_at', sa.BigInteger(), nullable=False), schema='app')
    op.create_table('meme_review_runs',
        sa.Column('id', sa.String(80), primary_key=True),
        sa.Column('finished_at', sa.BigInteger(), nullable=False),
        sa.Column('boards', JSONB(), nullable=False),
        sa.Column('context', JSONB(), nullable=False), schema='app')
    op.create_table('meme_review_drafts',
        sa.Column('owner', sa.String(128), primary_key=True),
        sa.Column('revision', sa.BigInteger(), nullable=False),
        sa.Column('edited_at', sa.BigInteger(), nullable=False),
        sa.Column('payload', JSONB(), nullable=False), schema='app')
    op.create_table('meme_review_publications',
        sa.Column('id', sa.String(80), primary_key=True),
        sa.Column('created_at', sa.BigInteger(), nullable=False),
        sa.Column('superseded_at', sa.BigInteger()), sa.Column('expires_at', sa.BigInteger()),
        sa.Column('payload', JSONB(), nullable=False), schema='app')
    op.create_table('meme_review_operations',
        sa.Column('id', sa.String(80), primary_key=True),
        sa.Column('owner', sa.String(128), nullable=False),
        sa.Column('created_at', sa.BigInteger(), nullable=False),
        sa.Column('retain_until', sa.BigInteger()),
        sa.Column('payload', JSONB(), nullable=False), schema='app')
    for name in ('state', 'runs', 'drafts', 'publications', 'operations'):
        op.execute(f'''DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='kichu_api') THEN
            GRANT SELECT, INSERT, UPDATE, DELETE ON app.meme_review_{name} TO kichu_api;
          END IF;
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='kichu_worker') THEN
            GRANT SELECT, INSERT, UPDATE, DELETE ON app.meme_review_{name} TO kichu_worker;
          END IF;
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='kichu_backup') THEN
            GRANT SELECT ON app.meme_review_{name} TO kichu_backup;
          END IF;
        END $$''')


def downgrade():
    for name in ('operations', 'publications', 'drafts', 'runs', 'state'):
        op.drop_table('meme_review_' + name, schema='app')
