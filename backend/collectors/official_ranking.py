"""Current official chart. Membership and position belong to the source."""
import re
import time
from uuid import uuid4

import requests
from services.collection_contracts import OfficialFetchResult, video_from_api

URL = 'https://api.bilibili.com/x/web-interface/ranking/v2'
SOURCE = 'bilibili_official_ranking_v2'


def fetch_official_ranking(*, request_get, headers, now, pause, attempt_id):
    started = int(now())
    attempt = dict(attempt_id=attempt_id, started_at=started, started_at_ns=time.time_ns(),
                   outcome='error', error_code=None, http_attempts=0)
    payload = None
    for index in range(2):
        attempt['http_attempts'] += 1
        try:
            response = request_get(URL, params={'rid':1007,'type':'all'}, headers=headers, timeout=10)
            if response.status_code != 200:
                attempt['error_code'] = f'http_{response.status_code}'
                if response.status_code >= 500 and index == 0:
                    pause(1.5)
                    continue
                break
            try:
                payload = response.json()
            except (ValueError, TypeError):
                attempt.update(outcome='invalid', error_code='invalid_json')
            break
        except (requests.Timeout, requests.ConnectionError):
            attempt['error_code'] = 'network'
            if index == 0:
                pause(1.5)
        except requests.RequestException:
            attempt['error_code'] = 'request_failed'
            break
    fetched = int(now())
    attempt['finished_at'] = fetched
    def reject(outcome, code):
        attempt.update(outcome=outcome, error_code=code)
        return OfficialFetchResult(None, attempt)
    if payload is None and attempt['error_code']:
        return OfficialFetchResult(None, attempt)
    if not isinstance(payload, dict):
        return reject('invalid', 'invalid_envelope')
    if payload.get('code') != 0:
        return reject('error', 'upstream_code')
    data = payload.get('data')
    if not isinstance(data, dict) or not isinstance(data.get('list'), list):
        return reject('invalid', 'invalid_list')
    source = data['list']
    if not source:
        return reject('empty', 'empty_chart')
    items, seen, anomalies = [], set(), []
    for rank, raw in enumerate(source, 1):
        bvid = raw.get('bvid') if isinstance(raw, dict) else None
        if not isinstance(bvid, str) or not re.fullmatch(r'BV[a-zA-Z0-9]{10}', bvid) or bvid in seen:
            anomalies.append(rank)
            continue
        seen.add(bvid)
        item = video_from_api(raw, endpoint='ranking_v2', observed_at=fetched)
        item['official_rank'] = rank
        items.append(item)
    if len(items) / len(source) < 0.9 or any(rank <= 20 for rank in anomalies):
        return reject('invalid', 'invalid_members')
    attempt.update(outcome='success', error_code=None)
    snapshot = dict(schema_version=1, snapshot_id=uuid4().hex, source=SOURCE,
                    rid=1007, type='all', fetched_at=fetched, upstream_updated_at=None,
                    source_count=len(source), item_count=len(items), display_limit=20,
                    partial=bool(anomalies), anomalies=anomalies, items=items,
                    started_at=started, started_at_ns=attempt['started_at_ns'], attempt_id=attempt_id)
    return OfficialFetchResult(snapshot, attempt)
