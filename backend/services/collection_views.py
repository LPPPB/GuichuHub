"""Pure public chart projections; persisted official identity always wins."""
from copy import deepcopy
from collectors.official_ranking import SOURCE


def select_collection_views(persisted,*,live,mode,now):
    live_data=(live or {}).get('data',{}) if live and 0<=now-live.get('cached_at',0)<=600 else {}
    if mode!='official':
        return deepcopy(dict(kichu_rank=live_data.get('kichu_rank',persisted.get('kichu_rank',[])),
            kichu_rank_meta={'source':'legacy_custom','status':'legacy','rules_version':'legacy'},
            hot_videos=live_data.get('hot_videos',persisted.get('hot_videos',[])),
            potential_meta={'source':'legacy_custom','status':'legacy','rules_version':'legacy'}))
    snapshot=persisted.get('official_kichu_snapshot') or {}
    valid=snapshot.get('source')==SOURCE and snapshot.get('rid')==1007 and snapshot.get('type')=='all'
    official=snapshot if valid else {}
    fetched=official.get('fetched_at')
    age=max(0,now-fetched) if fetched is not None else None
    meta={k:v for k,v in official.items() if k!='items'}
    meta.update(source=SOURCE,status='available' if valid else 'unavailable',
                stale=age is not None and age>3600,historical=age is not None and age>86400,
                last_attempt=persisted.get('official_kichu_attempt'))
    potential=persisted.get('potential_v2_snapshot')
    temporary=live_data.get('potential_v2_snapshot')
    if temporary is not None and (potential is None or temporary.get('meta',{}).get('fetched_at',0)>
                                  potential.get('meta',{}).get('fetched_at',0)):
        potential=temporary
    pmeta=dict((potential or {}).get('meta') or {})
    pmeta.update(source='independent_discovery',status='available' if potential is not None else 'unavailable',
                 last_attempt=live_data.get('potential_v2_attempt') or persisted.get('potential_v2_attempt'))
    return deepcopy(dict(kichu_rank=official.get('items',[])[:20],kichu_rank_meta=meta,
                         hot_videos=(potential or {}).get('items',[])[:30],potential_meta=pmeta))
