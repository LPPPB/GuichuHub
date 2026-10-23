"""Compose independent chart/discovery results and bounded legacy projections."""
from copy import deepcopy
from itertools import zip_longest
from collectors.discovery import discover_candidates,merge_video
from services.collection_contracts import STAT_KEYS,core_stat_sample,video_from_api
from services.potential_selection import generate_potential
from utils.scorer import calc_trend_score,get_trend_label,score_potential_batch,get_potential_reason


def _legacy_video(video,now):
    row=deepcopy(video)
    views=row.get('views') or 0
    if row.get('metrics_source')!='bilibili_stat':
        row['_stats_estimated']=True
        row['metrics_source']='estimated'
        for key in STAT_KEYS.values():
            row[key]=row.get(key) or 0
        row['likes']=int(views*0.05)
        row['shares']=int(views*0.01)
    row['trend_score']=calc_trend_score(*(row[key] for key in
        ('views','likes','coins','favorites','shares','comments','danmaku')),row.get('pub_date') or 0,now=now)
    row['trend_label']=get_trend_label(row['trend_score'])
    return row


def generate_collection(*,context,official_snapshot,pending,mode):
    from collectors import bilibili as bili
    now=context.now
    with context.activate():
        discovery=discover_candidates(context=context,official_snapshot=official_snapshot,pending=pending,now=now)
        strict=generate_potential(discovery,context=context,now=max(now,int(context.clock())),history=bili._smooth_online)
        now=max(now,int(context.clock()))
        derived={key:[_legacy_video(v,now) for v in values] for key,values in discovery.derived.items()}
        kichu,music,funny,popular=[derived[name] for name in ('kichu','music','funny','popular')]
        newest=[_legacy_video(v,now) for v in discovery.attempt.get('newest',[])]

        def enrich(video,online=False):
            if video.get('metrics_source')!='bilibili_stat':
                response=context.call('detail',video['bvid'],kind='detail')
                if response.outcome=='success' and isinstance(response.value,dict):
                    sample=core_stat_sample(response.value,endpoint='view',observed_at=response.observed_at or now)
                    if sample and response.value.get('bvid')==video['bvid']:
                        real=video_from_api(response.value,endpoint='view',observed_at=sample.observed_at)
                        video.update(merge_video(video,real))
            video.pop('_stats_estimated',None)
            if online:
                raw,precision,display=None,None,None
                if video.get('cid'):
                    response=context.call('online',video['bvid'],video['cid'],kind='online')
                    if response.outcome=='success' and isinstance(response.value,(tuple,list)) and len(response.value)==3:
                        raw,precision,display=response.value
                video.update(online_count_raw=raw,online_count=bili._smooth_online(video['bvid'],raw),
                             online_display=display,online_precision=precision,
                             online_observed_at=(response.observed_at or now) if raw is not None else None,
                             online_circuit_skipped=raw is None)
            video['trend_score']=calc_trend_score(*(video[key] for key in
                ('views','likes','coins','favorites','shares','comments','danmaku')),video.get('pub_date') or 0,now=now)
            video['trend_label']=get_trend_label(video['trend_score'])

        # Preserve legacy pre-gate behavior in shadow, including its relaxation.
        for video in newest:
            if not video['views']:
                enrich(video)
        legacy_pool=bili._deduplicate_by_bvid(kichu+newest+music+funny+popular)
        legacy_candidates,_=bili._filter_potential_candidates(legacy_pool,now)
        for video in legacy_candidates:
            enrich(video,online=True)
        over_cap=[]
        for video in legacy_pool:
            if video.get('tid') not in bili.KICHU_TIDS or int(video.get('views') or 0)<=bili.POTENTIAL_VIEWS_MAX:
                continue
            historical_online=bili._smooth_online(video['bvid'],None)
            if historical_online is None:
                continue
            video.update(online_count=historical_online,online_count_raw=None,online_circuit_skipped=True)
            over_cap.append(video)
        score_potential_batch(legacy_candidates,now,extra=over_cap)
        for video in legacy_candidates+over_cap:
            video['potential_reason']=get_potential_reason(video,now)
        legacy_candidates.sort(key=lambda v:-v['potential_score'])
        legacy_hot=legacy_candidates[:30]
        for video in music+funny:
            enrich(video)
        material=bili._filter_material_candidates(music,funny,now)
        # Tags only for already-selected derived samples, round-robin by source.
        tagged=set()
        for group in zip_longest(kichu,music,funny,popular):
            for video in group:
                if video is None or video['bvid'] in tagged:
                    continue
                tagged.add(video['bvid'])
                if not video.get('tags'):
                    response=context.call('tags',video['bvid'],kind='tags')
                    if response.outcome=='success' and isinstance(response.value,list):
                        video['tags']=[t for t in response.value if isinstance(t,str)]
        hot_memes=bili.get_hot_memes(kichu,music,funny,popular)
        hot_songs=bili.get_hot_songs(music,kichu)
        seeds=[_legacy_video(v,now) for v in discovery.attempt.get('seed_rows',[])]
        meme_materials=bili.get_meme_materials(bili._deduplicate_by_bvid(legacy_pool+seeds),hot_songs,
                                             seed_words=discovery.attempt.get('seed_words',[]))
        active_hot=(strict.snapshot or {}).get('items',[]) if mode=='official' else legacy_hot
        def bounded_detail(bvid):
            response=context.call('detail',bvid,kind='detail')
            return response.value if response.outcome=='success' and isinstance(response.value,dict) else None
        danmaku=bili.get_real_danmaku_words(
            bili._deduplicate_by_bvid(kichu[:20]+active_hot[:30]+material[:20]),
            detail_loader=bounded_detail)
        comments=bili.get_golden_comments(kichu[:10])

        found={}
        # Legacy rankings may contain videos older than the strict discovery window.
        # Register their parents too, so later lightweight observations can satisfy the FK.
        all_inputs=[v for lane in discovery.lanes.values() for v in lane]+legacy_pool+seeds
        all_inputs+=list((official_snapshot or {}).get('items',[]))+strict.evaluated
        for video in all_inputs:
            bvid=video['bvid']
            found[bvid]=merge_video(found.get(bvid),video)
        score_rows=strict.evaluated if mode=='official' else legacy_candidates+over_cap
        scores={v['bvid']:v for v in score_rows}
        visible={v['bvid'] for v in list((official_snapshot or {}).get('items',[]))[:20]+active_hot}
        for bvid,video in found.items():
            video.pop('potential_score',None)
            video.pop('potential_reason',None)
            if bvid in scores:
                video.update({key:scores[bvid][key] for key in ('potential_score','potential_reason')})
            video['_source']=','.join(sorted(set(video.get('sources',[])))) or 'official'
            video['observe_tier']='hot' if bvid in visible else 'warm'
            video['_preserve_tier']=bvid not in visible
        summary=dict(mode=mode,rules_version='strict-real-stats-v1',requests=context.summary(),
                     discovery_count=sum(map(len,discovery.lanes.values())),
                     legacy_count=len(legacy_hot),strict_count=len((strict.snapshot or {}).get('items',[])),
                     coverage=(strict.snapshot or {}).get('meta',{}).get('sources',{}),
                     rejected=(strict.snapshot or {}).get('meta',{}).get('rejected',{}),
                     duration_seconds=max(0,int(context.clock())-context.now))
        return dict(kichu_rank=kichu[:20],hot_videos=legacy_hot,hot_memes=hot_memes,hot_songs=hot_songs,
                    material_candidates=material,meme_materials=meme_materials,danmaku_words=danmaku,
                    comments_gold=comments,potential_v2_snapshot=strict.snapshot,
                    potential_v2_attempt=strict.attempt,potential_pending=strict.pending,
                    _potential_result=strict,_all_videos=list(found.values()),_collection_summary=summary)
