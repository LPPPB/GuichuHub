from copy import deepcopy
from tests.collection_samples import NOW
from tests.test_collection_state import result


def test_visible_snapshot_ignores_live_official_and_keeps_order():
    from services.collection_views import select_collection_views
    snapshot=result().snapshot
    snapshot['items']=[{'bvid':str(i),'official_rank':i+1} for i in range(100)]
    persisted={'official_kichu_snapshot':snapshot,'kichu_rank':[{'bvid':'old'}]}
    before=deepcopy(persisted)
    views=select_collection_views(persisted,live={'cached_at':NOW,'data':{'kichu_rank':[{'bvid':'live'}]}},mode='official',now=NOW)
    assert [v['bvid'] for v in views['kichu_rank']]==[str(i) for i in range(20)]
    assert views['kichu_rank_meta']['snapshot_id']==snapshot['snapshot_id']
    views['kichu_rank'][0]['bvid']='mutated'
    assert persisted==before


def test_missing_official_never_relabels_legacy():
    from services.collection_views import select_collection_views
    data={'kichu_rank':[{'bvid':'legacy'}]}
    assert select_collection_views(data,live=None,mode='official',now=NOW)['kichu_rank']==[]
    for mode in ('shadow','legacy'):
        views=select_collection_views(data,live=None,mode=mode,now=NOW)
        assert views['kichu_rank']==data['kichu_rank']
        assert views['kichu_rank_meta']['source']=='legacy_custom'
