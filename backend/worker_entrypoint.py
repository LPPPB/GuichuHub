"""Long-running entrypoint for scheduled and queued background work."""

from threading import Event, Thread

from jobs.calendar_jobs import ensure_calendar_worker
from jobs.crawl_jobs import _crawl_once
from jobs.scheduler import setup_scheduler
from logger import setup_logging
from storage.database import init_db


def run_worker():
    setup_logging()
    init_db()
    setup_scheduler()
    ensure_calendar_worker()
    Thread(target=_crawl_once, args=("startup",), daemon=True).start()
    Event().wait()


if __name__ == "__main__":
    run_worker()
