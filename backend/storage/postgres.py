"""Central SQLAlchemy engine and session-factory construction."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from storage.settings import DatabaseSettings


def create_session_factory(settings: DatabaseSettings) -> sessionmaker:
    engine = create_engine(settings.url, pool_pre_ping=True)
    return sessionmaker(bind=engine, expire_on_commit=False)
