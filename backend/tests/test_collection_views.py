from copy import deepcopy
from tests.collection_samples import NOW
from tests.test_collection_state import result
import pytest


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


@pytest.mark.parametrize('age,stale,historical',[(3600,False,False),(3601,True,False),(86400,True,False),(86401,True,True)])
def test_age_boundaries_and_attempt(age,stale,historical):
    from services.collection_views import select_collection_views
    snapshot=result(NOW-age).snapshot
    attempt={'outcome':'error','error_code':'timeout'}
    view=select_collection_views({'official_kichu_snapshot':snapshot,'official_kichu_attempt':attempt},live=None,mode='official',now=NOW)
    assert view['kichu_rank_meta']['stale'] is stale
    assert view['kichu_rank_meta']['historical'] is historical
    assert view['kichu_rank_meta']['last_attempt']==attempt


def potential(at,items=None,**extra):
    return {'items':items or [],'meta':dict(fetched_at=at,outcome='success',rules_version='strict-real-stats-v1',**extra)}


@pytest.mark.parametrize('change',[{'outcome':'error'},{'rules_version':'legacy'},{'outcome':None}])
def test_live_potential_requires_same_successful_rules(change):
    from services.collection_views import select_collection_views
    saved=potential(NOW-100,[{'bvid':'saved'}])
    temporary=potential(NOW,[{'bvid':'invalid'}]); temporary['meta'].update(change)
    view=select_collection_views({'potential_v2_snapshot':saved},live={'cached_at':NOW,'data':{'potential_v2_snapshot':temporary}},mode='official',now=NOW)
    assert view['hot_videos']==saved['items']


def test_newer_empty_success_wins_until_live_ttl_expires():
    from services.collection_views import select_collection_views
    saved=potential(NOW-100,[{'bvid':'saved'}])
    live={'cached_at':NOW,'data':{'potential_v2_snapshot':potential(NOW)}}
    for age,expected in [(600,[]),(601,saved['items'])]:
        view=select_collection_views({'potential_v2_snapshot':saved},live=live,mode='official',now=NOW+age)
        assert view['hot_videos']==expected
