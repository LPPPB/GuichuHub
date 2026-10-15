"""Candidate discovery is independent of official membership and local scores."""
from collections import deque
from copy import deepcopy
from itertools import zip_longest
from uuid import uuid4
import time

from config import KICHU_TIDS, MUSIC_TIDS, FUNNY_TIDS
from services.collection_contracts import DiscoveryResult, STAT_KEYS, classify_kichu, video_from_api

LANES = ('official','latest','search','newest','popular')
QUOTAS = dict(official=100,latest=100,search=100,newest=20,popular=80)
_METRICS = set(STAT_KEYS.values()) | {'metrics_source','metrics_endpoint','observed_at'}


def merge_video(existing, incoming):
    """Keep a complete sample together; merge provenance independently."""
    if existing is None:
        return deepcopy(incoming)
    result = deepcopy(existing)
    for key,value in incoming.items():
        if key not in _METRICS and key not in {'sources','first_seen'} and value not in (None,'',0,[]):
            result[key] = deepcopy(value)
    result['first_seen'] = min(existing.get('first_seen') or incoming.get('first_seen',0),
                               incoming.get('first_seen') or existing.get('first_seen',0))
    result['sources'] = sorted(set(existing.get('sources',[])) | set(incoming.get('sources',[])))
    if incoming.get('metrics_source') == 'bilibili_stat' and (
        existing.get('metrics_source') != 'bilibili_stat' or
        (incoming.get('observed_at') or 0) >= (existing.get('observed_at') or 0)):
        for key in _METRICS:
            result[key] = incoming.get(key)
    return result


def discover_candidates(*, context, official_snapshot, pending, now):
    policy = context.policy
    all_rows, memberships = {}, {name:set() for name in LANES}
    popular_rows, search_rows, seed_rows = [], [], []

    def add(video,lane,source=None):
        if not isinstance(video,dict) or not video.get('bvid'):
            return
        video = deepcopy(video)
        video.pop('official_rank',None)
        video['sources'] = sorted(set(video.get('sources',[])) | {source or lane})
        bvid = video['bvid']
        all_rows[bvid] = merge_video(all_rows.get(bvid),video)
        memberships[lane].add(bvid)

    def rows(name,*args,endpoint,lane=None):
        response = context.call(name,*args)
        if response.outcome != 'success' or not isinstance(response.value,list):
            return []
        normalized = [video_from_api(raw,endpoint=endpoint,observed_at=now)
                      for raw in response.value if isinstance(raw,dict) and raw.get('bvid')]
        if lane:
            for video in normalized:
                add(video,lane)
        return normalized

    for item in (official_snapshot or {}).get('items',[]):
        add(item,'official')
    for page in range(1,policy.popular_pages+1):
        popular_rows.extend(rows('popular_page',page,endpoint='popular',lane='popular'))
    queries = [('鬼畜',22),('音MAD',26),('人力',126),('鬼畜',216)]
    remaining = policy.kichu_search_pages
    for order,lane in [('pubdate','latest'),('totalrank','search')]:
        for keyword,tid in queries:
            for page in (1,2):
                if remaining <= 0:
                    break
                search_rows.extend(rows('search_page',keyword,tid,order,page,endpoint='search',lane=lane))
                remaining -= 1
    rows('all_ranking',endpoint='ranking_v2',lane='popular')
    newest = rows('newest',endpoint='newest',lane='newest')
    music_rows,funny_rows = [],[]
    for target,tid,words,cap in [
        (music_rows,3,['洗脑','翻唱','BGM','魔性','空耳','神曲','RAP'],policy.music_search_pages),
        (funny_rows,138,['名场面','洗脑','鬼畜','魔性','整活','空耳','恶搞'],policy.funny_search_pages),
    ]:
        for word in words[:cap]:
            target.extend(rows('search_page',word,tid,'pubdate',1,endpoint='search'))
        if callable(context.loaders.get('region_ranking')):
            target.extend(rows('region_ranking',tid,endpoint='region_ranking'))
    seed_loader = context.loaders.get('seed_words')
    seeds = seed_loader() if callable(seed_loader) else []
    seeds = [s for s in seeds if isinstance(s,str) and s.strip()]
    cursor = int(context.loaders.get('seed_cursor',0))
    seed_pages = 0
    visited = 0
    while seeds and visited < len(seeds) and seed_pages < policy.seed_search_pages:
        word = seeds[(cursor+visited)%len(seeds)]
        for page in (1,2):
            if seed_pages >= policy.seed_search_pages:
                break
            found = rows('search_page',word,22,'click',page,endpoint='search')
            for video in found:
                add(video,'search','meme_seed')
            seed_rows.extend(found)
            seed_pages += 1
        visited += 1
    for video in music_rows+funny_rows:
        add(video,'popular','material_source')
    for item in pending:
        if not isinstance(item,dict) or not item.get('bvid'):
            continue
        pub = item.get('pub_date') or 0
        if pub and now-pub > policy.age_days*86400:
            continue
        item = {**item,'_pending':True}
        source = next((name for name in item.get('sources',[]) if name in LANES),'latest')
        add(item,source,'pending')

    def eligible(video):
        pub = video.get('pub_date') or 0
        return classify_kichu(video) != 'ineligible' and (not pub or 0 <= now-pub <= policy.age_days*86400)
    candidates = {b:v for b,v in all_rows.items() if eligible(v)}
    queues = {}
    for lane in LANES:
        values = [candidates[b] for b in memberships[lane] if b in candidates]
        values.sort(key=lambda v:(-(v.get('pub_date') or 0),v['bvid']))
        retry = [v for v in values if v.get('_pending')]
        fresh = [v for v in values if not v.get('_pending')]
        queues[lane] = deque(v for pair in zip_longest(retry,fresh) for v in pair if v)
    selected,used = {lane:[] for lane in LANES},set()
    for respect_quota in (True,False):
        progress = True
        while progress and len(used)<policy.candidate_limit:
            progress = False
            for lane in LANES:
                if len(used)>=policy.candidate_limit:
                    break
                if respect_quota and len(selected[lane])>=QUOTAS[lane]:
                    continue
                while queues[lane] and queues[lane][0]['bvid'] in used:
                    queues[lane].popleft()
                if queues[lane]:
                    video = queues[lane].popleft()
                    selected[lane].append(video)
                    used.add(video['bvid'])
                    progress = True
    awaiting = [v for b,v in candidates.items() if b not in used or v.get('metrics_source')!='bilibili_stat']
    awaiting.sort(key=lambda v:(v.get('last_attempt_at',0),-(v.get('pub_date') or 0),v['bvid']))

    def legacy_sample(values,tids,limit=30,age=None):
        unique = {}
        for value in values:
            if value.get('tid') in tids and (age is None or 0<value.get('pub_date',0) and now-value['pub_date']<=age*86400):
                unique[value['bvid']] = merge_video(unique.get(value['bvid']),value)
        return sorted(unique.values(),key=lambda v:-(v.get('views') or 0))[:limit]
    derived = dict(kichu=legacy_sample(popular_rows+search_rows,KICHU_TIDS),
        music=legacy_sample(popular_rows[:150]+music_rows,MUSIC_TIDS,age=60),
        funny=legacy_sample(popular_rows[:150]+funny_rows,FUNNY_TIDS,age=60),
        popular=legacy_sample(popular_rows[:200],KICHU_TIDS,limit=50))
    events = [e for e in context.events if e['kind']=='discovery']
    attempt = dict(attempt_id=uuid4().hex,started_at=now,started_at_ns=time.time_ns(),finished_at=now,
        outcome='success' if any(e['outcome']=='success' for e in events) else 'error',
        partial=any(e['outcome']!='success' for e in events),
        failed_sources=[list(e['key']) for e in events if e['outcome']!='success'],
        seed_cursor=(cursor+visited)%len(seeds) if seeds else 0,seed_words=seeds,
        seed_rows=seed_rows, newest=newest)
    return DiscoveryResult(selected,derived,awaiting[:policy.pending_limit],attempt)
