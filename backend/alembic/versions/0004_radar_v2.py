"""Trusted observation metadata and immutable radar baselines."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0004_radar_v2'
down_revision = '0003_up_analysis_jobs'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('video_observations', sa.Column('metrics_source', sa.String(32),
                  nullable=False, server_default='legacy_unknown'), schema='app')
    for name in ('observed_at', 'online_observed_at'):
        op.add_column('video_observations', sa.Column(name, sa.BigInteger()), schema='app')
    op.add_column('video_observations', sa.Column('online_display', sa.Text()), schema='app')
    op.create_index('idx_video_observations_radar_time', 'video_observations',
                    ['bvid', 'observed_at'], schema='app')
    op.create_table('radar_baselines',
        sa.Column('version', sa.String(80), primary_key=True),
        sa.Column('algorithm_version', sa.String(32), nullable=False),
        sa.Column('cutoff_ts', sa.BigInteger(), nullable=False),
        sa.Column('valid_until', sa.BigInteger(), nullable=False),
        sa.Column('payload', JSONB(), nullable=False),
        sa.Column('created_at', sa.BigInteger(), nullable=False), schema='app')
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='kichu_api') THEN
        GRANT SELECT ON app.radar_baselines TO kichu_api;
      END IF;
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='kichu_worker') THEN
        GRANT SELECT, INSERT ON app.radar_baselines TO kichu_worker;
      END IF;
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='kichu_backup') THEN
        GRANT SELECT ON app.radar_baselines TO kichu_backup;
      END IF;
    END $$;""")


def downgrade():
    op.drop_table('radar_baselines', schema='app')
    op.drop_index('idx_video_observations_radar_time', table_name='video_observations', schema='app')
    for name in ('online_display', 'online_observed_at', 'observed_at', 'metrics_source'):
        op.drop_column('video_observations', name, schema='app')
