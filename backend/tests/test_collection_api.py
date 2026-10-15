from copy import deepcopy
from tests.collection_samples import NOW
from tests.test_collection_state import result


def test_dashboard_and_rank_share_persistent_snapshot_despite_live_cache(client,postgres_runtime,monkeypatch):
    import app as app_module
    snapshot=result().snapshot
    data={'official_kichu_snapshot':snapshot,'kichu_rank':[{'bvid':'legacy'}]}
    monkeypatch.setenv('COLLECTION_RULES_MODE','official')
    monkeypatch.setattr(app_module.time,'time',lambda:NOW)
    monkeypatch.setattr(app_module,'get_data',lambda:deepcopy(data))
    monkeypatch.setattr('storage.cache.get_live_cache',lambda:{'cached_at':NOW,'data':{'kichu_rank':[{'bvid':'live'}]}})
    app_module._invalidate_dashboard_payload()
    dashboard=client.get('/api/dashboard').json['data']
    rank=client.get('/api/kichu-rank').json
    assert [v['bvid'] for v in dashboard['kichu_rank']]==[v['bvid'] for v in rank['data']]==[snapshot['items'][0]['bvid']]
    assert dashboard['kichu_rank_meta']['snapshot_id']==rank['meta']['snapshot_id']
    assert data['official_kichu_snapshot']==snapshot
    # A new persistent snapshot must break the cache even with identical live timestamp.
    data['official_kichu_snapshot']={**snapshot,'snapshot_id':'new'}
    monkeypatch.setattr('storage.cache.get_data_version',lambda:99)
    assert client.get('/api/dashboard').json['data']['kichu_rank_meta']['snapshot_id']=='new'


def test_official_unavailable_is_distinct_from_http_failure(client,monkeypatch):
    import app as app_module
    monkeypatch.setenv('COLLECTION_RULES_MODE','official')
    monkeypatch.setattr(app_module,'get_data',lambda:{'kichu_rank':[{'bvid':'legacy'}]})
    app_module._invalidate_dashboard_payload()
    response=client.get('/api/kichu-rank')
    assert response.status_code==200 and response.json['success'] is True
    assert response.json['data']==[]
    assert response.json['meta']['status']=='unavailable'
