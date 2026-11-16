"""Transaction boundary for review documents; no shared data deletion."""
from copy import deepcopy
from contextlib import contextmanager
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from storage.models import meme_review_state as state, meme_review_runs as runs


class MemeReviewRepository:
    def __init__(self, sessions):
        self.sessions = sessions

    @contextmanager
    def locked(self, now):
        with self.sessions.begin() as session:
            session.execute(insert(state).values(id=1, revision=0, payload={}, updated_at=now)
                            .on_conflict_do_nothing(index_elements=[state.c.id]))
            row = session.execute(select(state).where(state.c.id == 1).with_for_update()).mappings().one()
            yield session, deepcopy(dict(row))

    def record_run(self, run_id, boards, now, context=None):
        with self.locked(now) as (session, current):
            session.execute(insert(runs).values(id=str(run_id), finished_at=now,
                boards=deepcopy(boards), context=context or {}).on_conflict_do_nothing(index_elements=[runs.c.id]))

    def get_run(self, run_id):
        with self.sessions() as session:
            row = session.execute(select(runs).where(runs.c.id == str(run_id))).mappings().first()
            return dict(row) if row else None
