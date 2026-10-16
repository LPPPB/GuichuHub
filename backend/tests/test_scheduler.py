from jobs import scheduler as scheduler_module
import pytest


@pytest.mark.parametrize('mode',['legacy','shadow','official'])
def test_official_schedule_is_independent(monkeypatch,mode):
    jobs=[]
    class Scheduler:
        def __init__(self,*,timezone): self.timezone=timezone
        def add_job(self,fn,trigger,**kw): jobs.append({'function':fn,'trigger':trigger,**kw})
        def start(self): pass
    monkeypatch.setattr(scheduler_module,'BackgroundScheduler',Scheduler)
    monkeypatch.setenv('COLLECTION_RULES_MODE',mode)
    scheduler=scheduler_module.setup_scheduler()
    official=[j for j in jobs if j['id']=='official_kichu_rank']
    assert str(scheduler.timezone)=='Asia/Shanghai'
    if mode=='legacy': assert official==[]
    else:
        assert official[0]['minute']=='5,35'
        assert official[0]['max_instances']==1 and official[0]['coalesce'] is True


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
