from alembic import context
from sqlalchemy import engine_from_config, pool

from storage.models import Base

config = context.config
target_metadata = Base.metadata


def run_migrations_online():
    engine = engine_from_config(config.get_section(config.config_ini_section), prefix="sqlalchemy.", poolclass=pool.NullPool)
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS app")
        context.configure(connection=connection, target_metadata=target_metadata, include_schemas=True, version_table_schema="app")
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
