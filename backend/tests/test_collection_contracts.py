import importlib
import importlib.util

import pytest
from tests.collection_samples import raw_video, NOW


def contracts():
    assert importlib.util.find_spec('services.collection_contracts'), 'collection contracts are missing'
    return importlib.import_module('services.collection_contracts')


@pytest.mark.parametrize('video,want', [
    ({'tid':219,'category_v2':{'pid':1007}}, 'eligible'),
    ({'tid':22,'category_v2':{'pid':1009,'tid':2063}}, 'ineligible'),
    ({'tid':219,'category_v2':{'tid':2063}}, 'eligible'),
    ({'tid':22,'category_v2':{'tid':9999}}, 'unknown'),
    ({'tid':'22'}, 'eligible'), ({'tid':138}, 'ineligible'),
])
def test_category_v2_parent_wins(video, want):
    assert contracts().classify_kichu(video) == want


@pytest.mark.parametrize('bad', [None, -1, True, float('nan'), 'bad', 1.2])
def test_complete_stats_reject_invalid(bad):
    row = raw_video()
    row['stat']['share'] = bad
    assert contracts().core_stat_sample(row, endpoint='view', observed_at=NOW) is None


def test_complete_stats_preserve_zero():
    sample = contracts().core_stat_sample(raw_video(stat={k:'0' for k in
        ('view','like','coin','favorite','share','reply','danmaku')}), endpoint='view', observed_at=NOW)
    assert sample.metrics == dict(views=0,likes=0,coins=0,favorites=0,shares=0,comments=0,danmaku=0)
    assert sample.observed_at == NOW
    assert contracts().core_stat_sample({'views':10000,'likes':500}, endpoint='search',observed_at=NOW) is None


def test_normalize_category_preserves_raw_version():
    assert contracts().normalize_category(raw_video()) == dict(tid=2063,tname='鬼畜综合',pid=1007,pid_name='鬼畜')


def test_policy_defaults_and_limits():
    import config
    assert hasattr(config, 'load_collection_policy'), 'policy loader is missing'
    policy = config.load_collection_policy({})
    assert (policy.mode, policy.candidate_limit, policy.detail_limit, policy.tag_limit) == ('shadow',400,160,64)
    assert (policy.discovery_limit,policy.refresh_seconds,policy.stale_seconds) == (60,1800,3600)
    for env in ({'COLLECTION_RULES_MODE':'bad'}, {'COLLECTION_DETAIL_LIMIT':'-1'}, {'OBSERVE_HOT_LIMIT':'49'}):
        with pytest.raises(ValueError):
            config.load_collection_policy(env)


def test_manual_scripts_import_without_http(monkeypatch):
    import requests
    calls = []
    def forbidden(*args, **kwargs):
        calls.append(args)
        raise AssertionError('manual script made HTTP during import')
    monkeypatch.setattr(requests, 'get', forbidden)
    import collectors.bilibili as bilibili
    monkeypatch.setattr(bilibili.time, 'sleep', lambda _: None)
    for name in ('tests.test_kichu_rank', 'tests.test_ranking'):
        importlib.import_module(name)
    assert calls == []
