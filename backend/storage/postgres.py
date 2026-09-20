"""Central SQLAlchemy engine and session-factory construction."""

from sqlalchemy import create_engine as _create_engine, event
from sqlalchemy.orm import sessionmaker

from storage.settings import DatabaseSettings


def create_engine(url, **options):
    """Hide binds and PostgreSQL diagnostic row values in ordinary tracebacks."""
    options["hide_parameters"] = True
    engine = _create_engine(url, **options)

    @event.listens_for(engine, "handle_error")
    def redact_database_error(context):
        original = context.original_exception
        code = getattr(original, "sqlstate", None)
        if code is None:
            # Python-side bind adaptation errors do not include database rows
            # or parameters, and callers rely on their validation type/message.
            return
        message = f"database operation failed ({type(original).__name__}, SQLSTATE {code})"
        # hide_parameters alone does not redact PostgreSQL DETAIL, which can
        # contain a failing row's cookies or token. Keep exception types/codes
        # for recovery, but remove values from both chained exception messages.
        original.args = (message,)
        if context.sqlalchemy_exception is not None:
            context.sqlalchemy_exception.args = (message,)
    return engine


def create_session_factory(settings: DatabaseSettings) -> sessionmaker:
    engine = create_engine(settings.url, pool_pre_ping=True)
    return sessionmaker(bind=engine, expire_on_commit=False)
