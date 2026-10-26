"""Blacklists must take effect on existing snapshots, including warm caches."""

from copy import deepcopy

import pytest

from collectors import bilibili as bili
from storage.repositories.state import StateRepository


@pytest.fixture
def snapshot(postgres_runtime, monkeypatch):
    import app as module

    data = {
        'hot_memes': [{'keyword': '哈基米'}, {'keyword': '哈基米南北绿豆'}],
        'meme_materials': [{'name': 'Hachimi'}, {'name': '面筋哥'}],
        'last_updated': '2026-10-25 15:02:40',
    }
    postgres_runtime.state.save_dashboard(data, 100)
    postgres_runtime.state.save_setting('meme_stopwords', {'自定义': ['未命中']}, 100)
    monkeypatch.setattr(module, 'WRITE_TOKEN', 'test-blacklist-token')
    monkeypatch.setattr('storage.cache.get_live_cache', lambda: None)
    module._invalidate_dashboard_payload()
    return data


def keywords(client, endpoint='/api/dashboard'):
    result = client.get(endpoint).json['data']
    rows = result['hot_memes'] if endpoint == '/api/dashboard' else result
    return [row['keyword'] for row in rows]


def test_saved_blacklist_filters_warm_dashboard_and_aliases_without_crawl(client, postgres_runtime, snapshot):
    assert keywords(client) == ['哈基米', '哈基米南北绿豆']
    before = deepcopy(snapshot)
    saved = client.put('/api/config/meme-stopwords',
                       headers={'X-Write-Token': 'test-blacklist-token'},
                       json={'categories': {'自定义': ['ＨＡＣＨＩＭＩ']}})
    assert saved.status_code == 200
    assert saved.json['effective'] == 'immediate'
    assert keywords(client) == ['哈基米南北绿豆']
    assert keywords(client, '/api/memes') == ['哈基米南北绿豆']
    assert [x['name'] for x in client.get('/api/meme-materials').json['data']] == ['面筋哥']
    assert postgres_runtime.state.load_dashboard() == before


def test_another_process_setting_write_filters_already_cached_payload(client, postgres_runtime, snapshot):
    assert keywords(client)[0] == '哈基米'
    writer = StateRepository(postgres_runtime.sessions)
    writer.save_setting('meme_stopwords', {'已屏蔽': ['哈 基 米']}, 101)
    assert keywords(client) == ['哈基米南北绿豆']
    writer.save_setting('meme_stopwords', {'自定义': ['未命中']}, 102)
    assert keywords(client) == ['哈基米', '哈基米南北绿豆']


def test_live_snapshot_is_filtered_without_being_mutated(client, postgres_runtime, snapshot, monkeypatch):
    live = deepcopy(snapshot)
    monkeypatch.setattr('storage.cache.get_live_cache', lambda: {'data': live, 'cached_at': 123})
    assert keywords(client)[0] == '哈基米'
    postgres_runtime.state.save_setting('meme_stopwords', {'自定义': ['Hachimi']}, 101)
    assert keywords(client) == ['哈基米南北绿豆']
    assert live == snapshot


def test_public_all_blocked_is_explicit_empty_not_unavailable(client, postgres_runtime, snapshot):
    postgres_runtime.state.save_setting('meme_stopwords', {'自定义': ['哈基米', '哈基米南北绿豆', '面筋哥']}, 101)
    result = client.get('/internal/public-pages').json['sections']
    assert result['memes']['status'] == 'empty'
    assert result['memes']['data']['hot_memes'] == []
    assert result['meme-materials']['status'] == 'empty'
    assert result['meme-materials']['data']['meme_materials'] == []


def test_status_exposes_cross_process_blacklist_revision(client, postgres_runtime, snapshot):
    initial = client.get('/api/status').json['data']['meme_rules_version']
    postgres_runtime.state.save_setting('meme_stopwords', {'自定义': ['Hachimi']}, 101)
    assert client.get('/api/status').json['data']['meme_rules_version'] > initial


def test_seed_cannot_override_explicit_meme_blacklist_or_its_alias(monkeypatch):
    monkeypatch.setattr(bili, 'load_meme_seed_words', lambda: ['哈基米'])
    monkeypatch.setattr(bili, 'load_meme_stopwords', lambda: {'人工屏蔽': ['Hachimi']})
    decision = bili.explain_hot_meme_rule('哈 基 米')
    assert decision['accepted'] is False
    assert decision['category'] == '人工屏蔽'


def test_blocklist_uses_whole_identity_and_never_mutates_rows(monkeypatch):
    from services.meme_visibility import filter_meme_sections

    monkeypatch.setattr(bili, 'load_meme_stopwords', lambda: {'人工屏蔽': ['Hachimi']})
    data = {'hot_memes': [{'keyword': '哈基米'}, {'keyword': '哈基米南北绿豆'}], 'other': [1]}
    before = deepcopy(data)
    assert filter_meme_sections(data)['hot_memes'] == [{'keyword': '哈基米南北绿豆'}]
    assert data == before
