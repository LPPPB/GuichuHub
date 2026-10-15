"""Long-running entrypoint for scheduled and queued background work."""

import os
import time
from threading import Event, Thread

from jobs.calendar_jobs import ensure_calendar_worker
from jobs.up_analysis_worker import ensure_analysis_worker
from jobs.collector_handoff import ensure_collector_handoff_worker
from jobs.crawl_jobs import _crawl_once
from jobs.official_ranking_jobs import refresh_official_if_due
from jobs.scheduler import setup_scheduler
from logger import setup_logging
from storage.database import init_db
from storage.health import HeartbeatService
from storage.runtime import configure_postgres_runtime


def run_worker():
    setup_logging()
    runtime = configure_postgres_runtime("worker")
    init_db()
    HeartbeatService(
        runtime.state.record_worker_heartbeat,
        worker_id=os.environ.get("KICHU_WORKER_ID", "worker"),
        details={"kind": "scheduler"},
    ).start()
    setup_scheduler()
    ensure_calendar_worker()
    ensure_analysis_worker()
    ensure_collector_handoff_worker()
    refresh_official_if_due(now=int(time.time()))
    Thread(target=_crawl_once, args=("startup",), daemon=True).start()
    Event().wait()


if __name__ == "__main__":
    run_worker()
