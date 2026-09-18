from jobs import scheduler as scheduler_module


def test_worker_scheduler_has_no_sqlite_backup_job(monkeypatch):
    jobs = []

    class FakeScheduler:
        def __init__(self, *, timezone):
            self.timezone = timezone

        def add_job(self, function, trigger, **kwargs):
            jobs.append({"function": function, "trigger": trigger, **kwargs})

        def start(self):
            pass

    monkeypatch.setattr(scheduler_module, "BackgroundScheduler", FakeScheduler)

    scheduler_module.setup_scheduler()

    assert "backup" not in {job["id"] for job in jobs}
    assert all("SQLite" not in job["name"] for job in jobs)
