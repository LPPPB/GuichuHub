"""Long-running repair work records resumable PostgreSQL progress."""

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from storage.migrations import upgrade_database
from storage.models import backfill_progress


def test_backfill_resumes_from_recorded_cursor_and_marks_completion(
    postgres_url, clean_postgres_data,
):
    from scripts.run_backfill import run_resumable_backfill

    upgrade_database(postgres_url)
    sessions = sessionmaker(bind=create_engine(postgres_url), expire_on_commit=False)
    seen = []

    def step(cursor):
        seen.append(cursor)
        return ({"offset": cursor.get("offset", 0) + 10}, len(seen) == 2)

    assert run_resumable_backfill(sessions, "history-repair", step, max_steps=1) is False
    assert run_resumable_backfill(sessions, "history-repair", step, max_steps=1) is True
    assert seen == [{}, {"offset": 10}]
    with sessions() as session:
        row = session.execute(select(backfill_progress).where(
            backfill_progress.c.name == "history-repair",
        )).mappings().one()
    assert row["status"] == "completed"
    assert row["cursor"] == {"offset": 20}
