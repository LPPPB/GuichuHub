import importlib.util
import importlib
from copy import deepcopy
import requests
import pytest
from tests.collection_samples import raw_video, rank_response, BVIDS, NOW


class Response:
    def __init__(self, value, status=200):
        self.value, self.status_code = value, status

    def json(self):
        if isinstance(self.value, Exception):
            raise self.value
        return deepcopy(self.value)


def fetch(response, calls=None):
    assert importlib.util.find_spec('collectors.official_ranking'), 'official collector missing'
    module = importlib.import_module('collectors.official_ranking')
    calls = [] if calls is None else calls
    def request(url, **kwargs):
        calls.append(kwargs)
        if isinstance(response, Exception):
            raise response
        return response
    return module.fetch_official_ranking(request_get=request, headers={},now=lambda: NOW,
                                        pause=lambda _: None, attempt_id='attempt-test')


def test_order_is_source_position_not_views():
    calls = []
    items = [raw_video(bvid,stat={**raw_video()['stat'],'view': views},tid=tid)
             for bvid,views,tid in zip(BVIDS,[1,3000000,100],[219,138,216])]
    result = fetch(Response(rank_response(items)), calls)
    assert [v['bvid'] for v in result.snapshot['items']] == BVIDS
    assert [v['official_rank'] for v in result.snapshot['items']] == [1,2,3]
    assert calls[0]['params'] == {'rid':1007,'type':'all'}
    assert len(calls) == 1
    assert result.snapshot['items'][0]['tid'] == 219
    assert result.snapshot['items'][0]['metrics_source'] == 'bilibili_stat'


@pytest.mark.parametrize('count',[3,93,100])
def test_variable_valid_length(count):
    result = fetch(Response(rank_response([raw_video(f'BV{i:010d}') for i in range(count)])))
    assert len(result.snapshot['items']) == count


@pytest.mark.parametrize('value,outcome', [
    ({'code':0,'data':{'list':[]}}, 'empty'),
    ({'code':-352}, 'error'),
    (ValueError('html'), 'invalid'), ([], 'invalid'), (None,'invalid'),
    ({'code':0,'data':None}, 'invalid'),
    ({'code':0,'data':{'list':'wrong'}}, 'invalid'),
])
def test_bad_response_does_not_publish(value,outcome):
    result = fetch(Response(value))
    assert result.snapshot is None
    assert result.attempt['outcome'] == outcome


@pytest.mark.parametrize('status,want',[(412,1),(429,1),(403,1),(500,2)])
def test_http_attempt_budget(status,want):
    calls=[]
    result=fetch(Response({},status),calls)
    assert result.snapshot is None
    assert len(calls) == want
    assert result.attempt['http_attempts'] == want


def test_timeout_retries_only_once():
    calls=[]
    assert fetch(requests.Timeout(),calls).snapshot is None
    assert len(calls)==2


def test_partial_anomaly_keeps_positions_after_top20():
    rows=[raw_video(f'BV{i:010d}') for i in range(100)]
    rows[25]['bvid']='invalid'
    result=fetch(Response(rank_response(rows)))
    assert result.snapshot['partial'] is True
    assert result.snapshot['items'][25]['official_rank']==27


def test_invalid_top20_or_large_loss_rejects_snapshot():
    rows=[raw_video(f'BV{i:010d}') for i in range(100)]
    rows[2]['bvid']=rows[0]['bvid']
    assert fetch(Response(rank_response(rows))).snapshot is None
    rows=[raw_video(f'BV{i:010d}') if i<80 else {} for i in range(100)]
    assert fetch(Response(rank_response(rows))).snapshot is None


def test_missing_optional_stat_is_unknown_without_dropping_member():
    row=raw_video(stat={})
    result=fetch(Response(rank_response([row])))
    item=result.snapshot['items'][0]
    assert item['bvid']==BVIDS[0] and item['views'] is None
    assert item['metrics_source']=='legacy_unknown'
