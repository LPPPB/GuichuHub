"""A potential score is earned after complete real statistics pass the gates."""
from collections import Counter,deque
from copy import deepcopy
from uuid import uuid4
from collectors.discovery import LANES,merge_video
from services.collection_contracts import PotentialResult, STAT_KEYS, classify_kichu, nonnegative_int, video_from_api
from utils.scorer import calc_engagement_quality,calc_trend_score,get_trend_label,score_potential_batch,get_potential_reason


def _fresh_stats(video,now):
    observed=video.get('observed_at')
    return (video.get('metrics_source')=='bilibili_stat' and isinstance(observed,int)
            and 0<=now-observed<=1800
            and all(nonnegative_int(video.get(key)) is not None for key in STAT_KEYS.values()))


def generate_potential(discovery, *, context, now, history):
    policy=context.policy
    now=max(now,int(context.clock()))
    attempt={key:deepcopy(value) for key,value in discovery.attempt.items()
             if key not in {'seed_rows','newest','seed_words'}}
    attempt.setdefault('attempt_id',uuid4().hex)
    attempt.setdefault('started_at',now)
    attempt.setdefault('started_at_ns',0)
    attempt['finished_at']=now
    if attempt.get('outcome')!='success':
        return PotentialResult(None,deepcopy(discovery.pending),attempt)
    lanes={lane:deque(deepcopy(discovery.lanes.get(lane,[]))) for lane in LANES}
    # Callers may supply one or more known lanes, never one official-only score pool.
    videos={v['bvid']:v for queue in lanes.values() for v in queue}
    awaiting={v['bvid']:deepcopy(v) for v in discovery.pending}
    attempted=set()

    def needs_detail(video):
        return not _fresh_stats(video,max(now,int(context.clock()))) or classify_kichu(video)=='unknown' or not video.get('pub_date')

    def enrich(video):
        bvid=video['bvid']
        if bvid in attempted or not needs_detail(video):
            return
        attempted.add(bvid)
        response=context.call('detail',bvid,kind='detail')
        if response.outcome!='budget':
            video['last_attempt_at']=int(context.clock())
        if response.outcome=='success' and isinstance(response.value,dict):
            real=video_from_api(response.value,endpoint='view',observed_at=response.observed_at or now)
            # A detail response must refer to the requested video, not a different BV.
            if real.get('bvid')==bvid:
                merged=merge_video(video,real)
                video.clear()
                video.update(merged)

    # Reserve space for recent discoveries before filling the remaining detail budget.
    for lane in ('newest','latest'):
        count=0
        for video in lanes[lane]:
            if needs_detail(video) and count<20:
                enrich(video)
                count+=1
    while any(lanes.values()):
        for lane in LANES:
            if lanes[lane]:
                enrich(lanes[lane].popleft())

    now=max(now,int(context.clock()))
    qualified=[]
    rejected=Counter()
    for bvid,video in videos.items():
        pub=video.get('pub_date') or 0
        category=classify_kichu(video)
        if category=='ineligible' or pub and not 0<=now-pub<=policy.age_days*86400:
            awaiting.pop(bvid,None)
            rejected['category_or_age']+=1
            continue
        if category!='eligible' or not pub or not _fresh_stats(video,now):
            awaiting[bvid]=video
            rejected['unverified']+=1
            continue
        awaiting.pop(bvid,None)
        if not policy.views_min<=video['views']<=policy.views_max:
            rejected['views']+=1
            continue
        if calc_engagement_quality(video)<policy.engagement_min:
            rejected['engagement']+=1
            continue
        video.pop('_pending',None)
        video.pop('official_rank',None)
        video['trend_score']=calc_trend_score(*(video[key] for key in
            ('views','likes','coins','favorites','shares','comments','danmaku')),pub,now=now)
        video['trend_label']=get_trend_label(video['trend_score'])
        raw,precision,display=None,None,None
        if video.get('cid'):
            response=context.call('online',bvid,video['cid'],kind='online')
            if response.outcome=='success' and isinstance(response.value,(list,tuple)) and len(response.value)==3:
                raw,precision,display=response.value
                raw=nonnegative_int(raw)
        video.update(online_count_raw=raw,online_count=history(bvid,raw),
                     online_precision=precision if raw is not None else None,
                     online_display=display if raw is not None else None,
                     online_observed_at=(response.observed_at or now) if raw is not None else None,
                     online_circuit_skipped=raw is None)
        qualified.append(video)
    score_potential_batch(qualified,now)
    for video in qualified:
        video['potential_reason']=get_potential_reason(video,now)
    qualified.sort(key=lambda v:(-v['potential_score'],-v['pub_date'],v['bvid']))
    pending=sorted(awaiting.values(),key=lambda v:(v.get('last_attempt_at',0),-(v.get('pub_date') or 0),v['bvid']))
    pending=[v for v in pending if not v.get('pub_date') or now-v['pub_date']<=policy.age_days*86400][:policy.pending_limit]
    attempt['finished_at']=max(now,int(context.clock()))
    meta={**attempt,'snapshot_id':uuid4().hex,'fetched_at':attempt['finished_at'],'batch_at':now,
          'rules_version':'strict-real-stats-v1','algorithm_version':'legacy-batch-minmax-v1',
          'thresholds':{key:getattr(policy,key) for key in ('views_min','views_max','engagement_min','age_days')},
          'candidate_count':len(videos),'qualified_count':len(qualified),'pending_count':len(pending),
          'rejected':dict(rejected),'sources':dict(Counter(s for v in videos.values() for s in v.get('sources',[]))),
          'partial':bool(attempt.get('partial')),'requests':context.summary()}
    return PotentialResult({'items':qualified[:30],'meta':meta},pending,attempt,qualified)
