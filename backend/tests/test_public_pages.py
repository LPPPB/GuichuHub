from copy import deepcopy
import json
from services.public_pages import build_public_sections, load_public_pages

VIDEO = {'bvid': 'BV1HYp16oE8v', 'title': '合成鬼畜榜作品', 'views': 0,
         'author': '公开作者', 'cookie': 'private-cookie', 'metadata': {'token': 'private-token'}}

def source():
    return {'kichu_rank': [VIDEO], 'hot_videos': [VIDEO],
            'hot_memes': [{'keyword': '合成热梗', 'heat': 9, 'related_videos': [VIDEO], 'token': 'private-token'}],
            'last_updated': '2026-10-18 10:00:00', 'favorites': ['private-favorite']}

def test_exports_only_explicit_public_nested_fields_without_mutating():
    data = source()
    before = deepcopy(data)
    out = build_public_sections(data, None)
    assert out['schema_version'] == 1
    assert out['sections']['kichu-rank']['data']['kichu_rank'][0]['views'] == 0
    assert out['sections']['memes']['data']['hot_memes'][0]['related_videos'][0]['title'] == '合成鬼畜榜作品'
    assert 'private-' not in json.dumps(out)
    assert data == before

def test_global_clock_and_private_fields_do_not_change_content_version():
    data = source()
    first = build_public_sections(data, None)
    data.update(last_updated='2026-10-19 12:00:00', token='private-new')
    second = build_public_sections(data, None)
    assert first['sections']['memes'] == second['sections']['memes']
    assert first['sections']['memes']['source_updated_at'] is None
    data['hot_memes'][0]['heat'] = 10
    assert first['sections']['memes']['content_version'] != build_public_sections(data, None)['sections']['memes']['content_version']


def test_material_related_songs_are_bounded_public_rows_and_affect_version():
    song = {'bvid': VIDEO['bvid'], 'name': '公开关联 BGM', 'plays': 10, 'cookie': 'private-cookie'}
    data = {'meme_materials': [{'name': '公开素材', 'related_songs': [song] * 21}]}
    first = build_public_sections(data, None)['sections']['meme-materials']
    rows = first['data']['meme_materials'][0]['related_songs']
    assert len(rows) == 20
    assert rows[0]['name'] == '公开关联 BGM'
    assert rows[0]['plays'] == 10
    assert 'private-' not in json.dumps(rows)
    song['plays'] = 20
    assert first['content_version'] != build_public_sections(data, None)['sections']['meme-materials']['content_version']

def test_up_timeline_is_bounded_and_projects_only_public_statistics():
    up = {'created_at': 1792300000, 'analysis': {'timeline': [
        {'date': '2026-10-18', 'count': 0, 'views': 30, 'token': 'private-token'}] * 61}}
    rows = build_public_sections({}, up)['sections']['up-trends']['data']['up_analysis']['analysis']['timeline']
    assert len(rows) == 60
    assert rows[0] == {'date': '2026-10-18', 'count': 0, 'views': 30}

def test_real_up_producer_shapes_survive_public_projection():
    up = {'created_at': 1792300000, 'analysis': {
        'keyword_cloud': [{'text': '真实公开热词', 'value': 42, 'token': 'private-token'}],
        'content_types': [{'type': '鬼畜调教', 'count': 3, 'token': 'private-token'}],
        'timeline': [{'date': '10-18', 'count': 2, 'views': 300, 'token': 'private-token'}]}}
    analysis = build_public_sections({}, up)['sections']['up-trends']['data']['up_analysis']['analysis']
    assert analysis['keyword_cloud'] == [{'text': '真实公开热词', 'value': 42}]
    assert analysis['content_types'] == [{'type': '鬼畜调教', 'count': 3}]
    assert analysis['timeline'] == [{'date': '10-18', 'count': 2, 'views': 300}]

def test_persisted_online_observation_is_never_published_as_current_live_count():
    row = dict(VIDEO, online_count=99, online_count_raw=None, online_circuit_skipped=True)
    result = build_public_sections({'kichu_rank': [row]}, None)['sections']['kichu-rank']['data']['kichu_rank'][0]
    assert result['online_count'] == 99
    assert result['online_circuit_skipped'] is True

def test_ambiguous_empty_and_malformed_sections_are_unavailable():
    for value in [[], None, 'broken', [{'title': 'no bvid'}]]:
        out = build_public_sections({'kichu_rank': value}, None)
        assert out['sections']['kichu-rank']['status'] == 'unavailable'
    out = build_public_sections({'kichu_rank': [dict(VIDEO, views=float('nan'), cover='https://evil.example/a.png')]}, None)
    row = out['sections']['kichu-rank']['data']['kichu_rank'][0]
    assert row.get('views') is None
    assert row.get('cover') is None

def test_bounds_fields_rows_and_nested_related_videos():
    data = source()
    data['kichu_rank'] = [dict(VIDEO, title='文'*600, description='x'*5000)] * 201
    data['hot_memes'][0]['related_videos'] = [VIDEO]*21
    out = build_public_sections(data, None)
    rows = out['sections']['kichu-rank']['data']['kichu_rank']
    assert len(rows) == 200
    assert len(rows[0]['title']) == 500
    assert len(rows[0]['description']) == 4000
    assert len(out['sections']['memes']['data']['hot_memes'][0]['related_videos']) == 20

def test_rejects_oversized_export_instead_of_returning_truncated_json():
    import pytest
    data = {'kichu_rank': [dict(VIDEO, description='字'*4000)] * 200}
    with pytest.raises(ValueError, match='byte limit'):
        build_public_sections(data, None)

def test_loader_isolates_source_failures_and_never_reads_live(monkeypatch):
    import storage.cache
    import storage.up_trends_reader
    monkeypatch.setattr('services.public_pages._with_public_observed_statistics', lambda value: value, raising=False)
    monkeypatch.setattr(storage.cache, 'get_data', source)
    monkeypatch.setattr(storage.cache, 'get_live_cache', lambda: (_ for _ in ()).throw(AssertionError('LIVE accessed')))
    monkeypatch.setattr(storage.up_trends_reader, 'load_analysis', lambda: (_ for _ in ()).throw(RuntimeError('UP offline')))
    assert load_public_pages()['sections']['kichu-rank']['status'] == 'ready'


def test_loader_uses_latest_persisted_statistics_without_changing_rank_scores(monkeypatch):
    from types import SimpleNamespace
    import storage.cache
    import storage.up_trends_reader
    import storage.repositories.radar
    from utils.radar_v2 import COUNTS
    data = source()
    original = deepcopy(data)
    latest = {key: 1 for key in COUNTS}
    latest.update(views=260000, observed_at=1792300000, metrics_source='bilibili_stat')
    monkeypatch.setattr(storage.cache, 'get_data', lambda: data)
    monkeypatch.setattr(storage.up_trends_reader, 'load_analysis', lambda: None)
    monkeypatch.setattr(storage.repositories.radar, 'get_radar_repository', lambda: SimpleNamespace(
        video_contexts=lambda ids, now: {VIDEO['bvid']: {'latest': latest}}))
    row = load_public_pages()['sections']['kichu-rank']['data']['kichu_rank'][0]
    assert row['views'] == 260000
    assert row['observed_at'] == 1792300000
    assert data == original


def test_statistics_read_failure_retains_video_sources_and_keeps_other_sections(monkeypatch):
    import storage.cache
    import storage.up_trends_reader
    import storage.repositories.radar
    monkeypatch.setattr(storage.cache, 'get_data', source)
    monkeypatch.setattr(storage.up_trends_reader, 'load_analysis', lambda: None)
    monkeypatch.setattr(storage.repositories.radar, 'get_radar_repository', lambda: (_ for _ in ()).throw(RuntimeError('offline')))
    result = load_public_pages()['sections']
    assert result['kichu-rank']['status'] == 'unavailable'
    assert result['memes']['status'] == 'ready'

def test_exports_other_sections_and_up_analysis_with_independent_version():
    data = source()
    data.update(hot_songs=[{'bvid': VIDEO['bvid'], 'name': '公开曲目', 'artist': '作者'}],
                meme_materials=[{'name': '公开素材', 'related_videos': [VIDEO], 'request_reason': 'private-reason'}],
                material_candidates=[VIDEO], danmaku_words=[{'word': '公开热词', 'count': 10}],
                comments_gold=[{'content': '公开评论', 'source_bvid': VIDEO['bvid'], 'token': 'private-token'}])
    up = {'created_at': 1792300000, 'analysis': {'summary': {'total_ups': 1, 'token': 'private-token'},
          'hot_videos': [VIDEO], 'play_ranking': [{'mid': 123, 'name': '公开作者', 'request': 'private-reason'}]},
          'up_details': [{'mid': 123, 'name': '公开作者', 'request_reason': 'private-reason'}]}
    first = build_public_sections(data, up)
    for tab in ['meme-materials', 'songs', 'materials', 'danmaku', 'up-trends']:
        assert first['sections'][tab]['status'] == 'ready'
    assert 'private-' not in json.dumps(first)
    assert first['sections']['up-trends']['source_updated_at'] == 1792300000
    up['analysis']['summary']['total_ups'] = 2
    second = build_public_sections(data, up)
    assert first['sections']['up-trends']['content_version'] != second['sections']['up-trends']['content_version']
    assert first['sections']['memes'] == second['sections']['memes']
