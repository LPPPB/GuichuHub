"""get_kichu_videos 采集过滤逻辑单元测试。

用 monkeypatch mock 网络层(fetch_*),验证:
- typeid 二次过滤(字符串转 int)
- 一年老视频过滤
- 防御性过滤(tid∉KICHU_TIDS 丢弃)
- 返回 ≤30 条、按 views 降序
不依赖真实网络。
"""
import time
import pytest
from collectors.bilibili import get_kichu_videos, KICHU_TIDS


def _popular_video(bvid, tid, views=100000, pubdate=None):
    """构造 popular feed / ranking API 风格的 video dict"""
    return {
        'bvid': bvid,
        'aid': 1,
        'title': f'视频{bvid}',
        'description': '',
        'pic': '//i0.hdslb.com/test.jpg',
        'tid': tid,
        'tname': '鬼畜调教',
        'duration': 120,
        'pubdate': pubdate or int(time.time()),
        'stat': {
            'view': views, 'danmaku': 10, 'reply': 5,
            'like': 100, 'coin': 50, 'favorite': 30, 'share': 10,
        },
        'owner': {'name': 'UP主', 'mid': 1},
    }


def _search_video(bvid, typeid, views=100000, pubdate=None):
    """构造搜索 API 风格的 video dict(typeid 字符串、stat 平铺)"""
    return {
        'bvid': bvid,
        'aid': 1,
        'title': f'搜索{bvid}',
        'author': '搜索UP',
        'mid': 1,
        'pic': '//i0.hdslb.com/search.jpg',
        'description': '',
        'typename': '鬼畜调教',
        'typeid': str(typeid),  # 搜索 API 返回字符串
        'play': views,
        'video_review': 10,
        'review': 5,
        'favorites': 30,
        'coins': 50,
        'pts': 0,
        'duration': '2:00',
        'pubdate': pubdate or int(time.time()),
        'tag': '鬼畜,空耳',
    }


@pytest.fixture
def mock_fetch(monkeypatch):
    """mock bilibili 模块的网络层函数,返回可控数据"""
    import collectors.bilibili as bilibili

    def _setup(popular_videos=None, search_videos=None, ranking_videos=None):
        # fetch_popular_multi 返回 popular feed 数据
        monkeypatch.setattr(bilibili, 'fetch_popular_multi',
                            lambda pages=3, ps=50: popular_videos or [])
        # fetch_search_videos_by_keyword 按关键词返回搜索结果
        search_map = search_videos or {}
        def _fake_search(kw, tid, pages=2, ps=20, order='pubdate'):
            return search_map.get((kw, tid), [])
        monkeypatch.setattr(bilibili, 'fetch_search_videos_by_keyword', _fake_search)
        # fetch_ranking_v2 返回全站榜
        monkeypatch.setattr(bilibili, 'fetch_ranking_v2',
                            lambda rid=0: ranking_videos or [])
        # fetch_video_tags 返回空(避免网络)
        monkeypatch.setattr(bilibili, 'fetch_video_tags', lambda bvid: [])
        # 抑制 time.sleep 加速测试
        monkeypatch.setattr(bilibili, 'time', type('T', (), {
            'sleep': staticmethod(lambda s: None),
            'time': staticmethod(lambda: int(time.time())),
        })())

    return _setup


def test_get_kichu_videos_filters_non_kichu_tid(mock_fetch):
    """popular feed 中 tid 不在 KICHU_TIDS 的视频应被过滤"""
    mock_fetch(popular_videos=[
        _popular_video('BV1', 22, views=100000),    # 鬼畜调教 ✓
        _popular_video('BV2', 26, views=200000),    # 音MAD ✓
        _popular_video('BV3', 138, views=999999),   # 搞笑区 ✗
        _popular_video('BV4', 21, views=888888),    # 日常 ✗
    ])
    result = get_kichu_videos()
    bvids = [v['bvid'] for v in result]
    assert 'BV1' in bvids
    assert 'BV2' in bvids
    assert 'BV3' not in bvids  # 搞笑区被过滤
    assert 'BV4' not in bvids  # 日常被过滤


def test_get_kichu_videos_typeid_string_to_int(mock_fetch):
    """搜索 API typeid 是字符串,应转 int 后与 KICHU_TIDS 比较。
    回归测试:之前 '22' not in {22,...} 导致搜索结果全部被误杀。
    """
    mock_fetch(search_videos={
        ('鬼畜', 22): [
            _search_video('BVS1', typeid=22, views=100000),   # 字符串'22' → int 22 ✓
            _search_video('BVS2', typeid=138, views=999999),  # 非鬼畜 ✗
        ],
    })
    result = get_kichu_videos()
    bvids = [v['bvid'] for v in result]
    assert 'BVS1' in bvids   # typeid='22' 应被正确识别
    assert 'BVS2' not in bvids


def test_get_kichu_videos_typeid_empty_dropped(mock_fetch):
    """typeid 为空的视频应被丢弃(宁可错杀不漏)"""
    mock_fetch(search_videos={
        ('鬼畜', 22): [
            _search_video('BVS1', typeid=None, views=999999),
            _search_video('BVS2', typeid='', views=999999),
        ],
    })
    result = get_kichu_videos()
    bvids = [v['bvid'] for v in result]
    assert 'BVS1' not in bvids
    assert 'BVS2' not in bvids


def test_get_kichu_videos_old_video_filtered(mock_fetch):
    """搜索源:一年以上的老视频应被过滤"""
    now = int(time.time())
    one_year_ago = now - 365 * 86400
    mock_fetch(search_videos={
        ('鬼畜', 22): [
            _search_video('BVNEW', typeid=22, views=100000, pubdate=now - 86400),       # 1天前 ✓
            _search_video('BVOLD', typeid=22, views=999999, pubdate=one_year_ago - 86400),  # 1年+1天前 ✗
        ],
    })
    result = get_kichu_videos()
    bvids = [v['bvid'] for v in result]
    assert 'BVNEW' in bvids
    assert 'BVOLD' not in bvids


def test_get_kichu_videos_defensive_filter(mock_fetch):
    """防御性过滤:即使某源漏过非鬼畜 tid 的视频,返回前也应被丢弃。
    通过 ranking 源注入 tid=138(搞笑)的视频,验证被防御性过滤。
    """
    mock_fetch(ranking_videos=[
        _popular_video('BVR1', 22, views=100000),    # 鬼畜 ✓
        _popular_video('BVR2', 216, views=200000),   # 鬼畜剧场 ✓
        _popular_video('BVR3', 138, views=999999),   # 搞笑 ✗ 应被防御性过滤
    ])
    result = get_kichu_videos()
    bvids = [v['bvid'] for v in result]
    assert 'BVR1' in bvids
    assert 'BVR2' in bvids
    assert 'BVR3' not in bvids


def test_get_kichu_videos_dedup_across_sources(mock_fetch):
    """跨源去重:同一 bvid 在 popular 和 ranking 都出现,只保留一份"""
    mock_fetch(
        popular_videos=[_popular_video('BVDUP', 22, views=100000)],
        ranking_videos=[_popular_video('BVDUP', 22, views=100000)],
    )
    result = get_kichu_videos()
    bvids = [v['bvid'] for v in result]
    assert bvids.count('BVDUP') == 1


def test_get_kichu_videos_sorted_by_views_desc(mock_fetch):
    """结果应按 views 降序"""
    mock_fetch(popular_videos=[
        _popular_video('BV1', 22, views=100000),
        _popular_video('BV2', 22, views=500000),
        _popular_video('BV3', 22, views=300000),
    ])
    result = get_kichu_videos()
    views_list = [v['views'] for v in result]
    assert views_list == sorted(views_list, reverse=True)


def test_get_kichu_videos_max_30(mock_fetch):
    """返回最多 30 条"""
    popular = [_popular_video(f'BV{i:02d}', 22, views=100000 - i) for i in range(40)]
    mock_fetch(popular_videos=popular)
    result = get_kichu_videos()
    assert len(result) <= 30


def test_get_kichu_videos_all_in_kichu_tids(mock_fetch):
    """返回的所有视频 tid 必须在 KICHU_TIDS 中(终极断言)"""
    mock_fetch(
        popular_videos=[
            _popular_video('BV1', 22),
            _popular_video('BV2', 26),
            _popular_video('BV3', 126),
            _popular_video('BV4', 216),
            _popular_video('BV5', 138),  # 非鬼畜
        ],
        search_videos={
            ('鬼畜', 22): [_search_video('BVS1', typeid=22)],
            ('音MAD', 26): [_search_video('BVS2', typeid=26)],
        },
        ranking_videos=[_popular_video('BVR1', 21)],  # 非鬼畜
    )
    result = get_kichu_videos()
    for v in result:
        assert v['tid'] in KICHU_TIDS, f"非鬼畜视频混入: bvid={v['bvid']} tid={v['tid']}"


def test_get_kichu_videos_empty_input(mock_fetch):
    """所有源都为空时返回空列表,不崩溃"""
    mock_fetch()
    result = get_kichu_videos()
    assert result == []


def test_get_kichu_videos_covers_four_subcategories(mock_fetch):
    """4 个鬼畜子分区(22/26/126/216)的视频都应能被采集"""
    mock_fetch(
        popular_videos=[
            _popular_video('BVP22', 22, views=400000),
            _popular_video('BVP26', 26, views=300000),
            _popular_video('BVP126', 126, views=200000),
            _popular_video('BVP216', 216, views=100000),
        ],
    )
    result = get_kichu_videos()
    tids = {v['tid'] for v in result}
    assert {22, 26, 126, 216}.issubset(tids), f'未覆盖全部子分区: {tids}'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
