"""Worker-only official chart refreshes, using the shared collection session."""
from datetime import datetime, timedelta
import os
import time
import requests
from uuid import uuid4
from config import load_collection_policy
from collectors.official_ranking import fetch_official_ranking
from collectors.bilibili import get_headers
from jobs.collection_lock import get_collection_lock, CollectionLockLost
from storage.cache import get_data
from storage.repositories.collection_state import get_collection_repository
from services.collection_contracts import OfficialFetchResult
from logger import get_logger

logger=get_logger(__name__)
_scheduler=None


def configure_scheduler(scheduler):
    global _scheduler
    _scheduler=scheduler


def select_observation_targets(visible,tiered,*,limit):
    return list(dict.fromkeys(visible+tiered))[:limit]


def run_official_ranking_job(trigger='scheduled'):
    if load_collection_policy(os.environ).mode=='legacy':
        return {'status':'disabled'}
    guard=get_collection_lock().try_acquire(trigger=f'official:{trigger}')
    if guard is None:
        logger.info('Official ranking refresh skipped_busy (%s)',trigger)
        if trigger!='retry' and _scheduler is not None:
            _scheduler.add_job(run_official_ranking_job,'date',
                run_date=datetime.now(_scheduler.timezone)+timedelta(minutes=5),
                args=('retry',),id='official_kichu_rank_retry',replace_existing=True,
                max_instances=1,coalesce=True)
        return {'status':'skipped_busy'}
    with guard:
        result=fetch_official_ranking(request_get=requests.get,headers=get_headers(),now=time.time,pause=time.sleep,attempt_id=uuid4().hex)
        try:
            get_collection_repository().publish_official(result,guard=guard)
        except CollectionLockLost:
            raise
        except Exception as error:
            # Metadata must exist before cards become visible. Keep last success.
            logger.warning('Official publication failed: %s',type(error).__name__)
            guard.assert_held()
            attempt={**result.attempt,'outcome':'error','error_code':'metadata_publication_failed'}
            get_collection_repository().publish_official(OfficialFetchResult(None,attempt),guard=guard)
            return {'status':'error'}
        return {'status':result.attempt['outcome']}


def refresh_official_if_due(*,now):
    policy=load_collection_policy(os.environ)
    if policy.mode=='legacy': return {'status':'disabled'}
    snapshot=(get_data() or {}).get('official_kichu_snapshot') or {}
    age=now-snapshot.get('fetched_at',0)
    if snapshot and 0<=age<=policy.refresh_seconds:
        return {'status':'fresh'}
    return run_official_ranking_job('startup')
