"""UP 卡片功能单元测试（词云 + 分区 top3 + 缓存）。

用 monkeypatch mock 网络层（safe_get_with_wbi）与缓存读写，验证：
- VIDEO_TYPE_MAP 鬼畜分区映射正确
- _calc_video_types 按投稿量 top3、未知分区过滤
- fetch_up_full_videos 翻页逻辑（count 到底提前退出）
- get_up_card 缓存命中不翻页 / 未命中抓取并写缓存
不依赖真实网络与 DB。
"""
import time
import pytest
from collectors.bilibili_user import get_up_card, _calc_video_types, VIDEO_TYPE_MAP


def _vlist_item(bvid, typeid, title='', created=None, desc='', play=0):
    """构造 arc/search vlist 条目"""
    return {
        'bvid': bvid,
        'typeid': typeid,
        'title': title or f'视频{bvid}',
        'description': desc,
        'created': created or int(time.time()),
        'play': play,
    }


def test_video_type_map_has_kichu():
    """鬼畜分区映射（biliscope 同款）"""
    assert VIDEO_TYPE_MAP['22'] == '鬼畜调教'
    assert VIDEO_TYPE_MAP['26'] == '音MAD'
    assert VIDEO_TYPE_MAP['126'] == '人力VOCALOID'
    assert VIDEO_TYPE_MAP['216'] == '鬼畜剧场'


def test_calc_video_types_top3():
    """按投稿量排序取 top3，映射中文名"""
    videos = [
        _vlist_item('B1', 22), _vlist_item('B2', 22), _vlist_item('B3', 22),
        _vlist_item('B4', 26), _vlist_item('B5', 26),
        _vlist_item('B6', 216),
    ]
    types = _calc_video_types(videos)
    assert [t['tid'] for t in types] == [22, 26, 216]
    assert types[0]['name'] == '鬼畜调教'
    assert types[0]['count'] == 3
    assert types[0]['link'] == 'kichiku/guide'


def test_calc_video_types_unknown_tid_skipped():
    """未知分区 id 应被过滤（不输出空名标签）"""
    videos = [_vlist_item('B1', 99999), _vlist_item('B2', 22)]
    types = _calc_video_types(videos)
    assert [t['tid'] for t in types] == [22]


def test_calc_video_types_empty():
    """空列表返回空，不崩溃"""
    assert _calc_video_types([]) == []


def test_fetch_up_full_videos_pagination(monkeypatch):
    """翻页逻辑：count 到底提前退出，累计全部 vlist"""
    import collectors.bilibili_user as bu
    calls = []

    def fake_fetch(url, params):
        pn = params['pn']
        calls.append(pn)
        if pn == 1:
            vlist = [_vlist_item(f'B{i}', 22) for i in range(30)]
            count = 35
        else:
            vlist = [_vlist_item(f'B{i}', 26) for i in range(30, 35)]
            count = 35
        return {'error': None, 'data': {'list': {'vlist': vlist}, 'page': {'count': count}}}

    monkeypatch.setattr(bu, 'safe_get_with_wbi', fake_fetch)
    monkeypatch.setattr(bu, 'time', type('T', (), {'sleep': staticmethod(lambda s: None)})())
    videos, total = bu.fetch_up_full_videos(1, max_pages=10)
    assert len(videos) == 35
    assert total == 35  # 透出接口真实投稿总数
    assert calls == [1, 2]  # 第 2 页后 count 到底，不再翻第 3 页


def test_fetch_up_full_videos_error_breaks(monkeypatch):
    """接口报错（error 非空）应中断翻页"""
    import collectors.bilibili_user as bu
    calls = []

    def fake_fetch(url, params):
        calls.append(params['pn'])
        return {'error': '登录状态失效'}

    monkeypatch.setattr(bu, 'safe_get_with_wbi', fake_fetch)
    videos, total = bu.fetch_up_full_videos(1, max_pages=10)
    assert videos == []
    assert total == 0
    assert calls == [1]


def test_get_up_card_uses_cache(monkeypatch):
    """缓存命中时不翻页直接返回缓存数据"""
    import collectors.bilibili_user as bu
    import storage.up_card_store as store

    card = {'mid': 1, 'video_count': 0, 'word_cloud': [], 'video_types': [], 'last_7d_count': 0, 'last_7d_views': 0, 'latest_pub_ts': 0}
    monkeypatch.setattr(store, 'read_up_card_cache', lambda mid: card)
    monkeypatch.setattr(bu, 'fetch_up_full_videos',
                        lambda mid, max_pages=10: (_ for _ in ()).throw(AssertionError('缓存命中不应翻页')))
    result = get_up_card(1)
    assert result == card


def test_get_up_card_fetches_and_writes(monkeypatch):
    """未命中缓存：翻页抓取 → 组装卡片 → 写缓存"""
    import collectors.bilibili_user as bu
    import storage.up_card_store as store

    monkeypatch.setattr(store, 'read_up_card_cache', lambda mid: None)
    written = {}
    monkeypatch.setattr(store, 'write_up_card_cache', lambda mid, card: written.update({mid: card}))
    videos = [
        _vlist_item('B1', 22, title='哈基米 大狗叫', created=int(time.time()) - 86400, play=1000),
        _vlist_item('B2', 22, title='大狗叫 原曲', created=int(time.time()) - 3600, play=2000),
        _vlist_item('B3', 26, title='音MAD 卡点', created=int(time.time()) - 10 * 86400, play=500),
    ]
    monkeypatch.setattr(bu, 'fetch_up_full_videos', lambda mid, max_pages=10: (videos, len(videos)))

    card = get_up_card(1)
    assert card['video_count'] == 3
    assert [t['tid'] for t in card['video_types']] == [22, 26]
    # 近7天窗口：B1(-1天)/B2(-1小时) 在内，B3(-10天) 在窗口外不计入
    assert card['last_7d_count'] == 2
    assert card['last_7d_views'] == 3000  # 近7天真实总播放（play 之和，不按合作者平分）
    assert written[1]['mid'] == 1  # 已写缓存


def test_get_up_card_empty_returns_none(monkeypatch):
    """无投稿时返回 None（不写缓存）"""
    import collectors.bilibili_user as bu
    import storage.up_card_store as store

    monkeypatch.setattr(store, 'read_up_card_cache', lambda mid: None)
    monkeypatch.setattr(bu, 'fetch_up_full_videos', lambda mid, max_pages=10: ([], 0))
    assert get_up_card(1) is None


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
