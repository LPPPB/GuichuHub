"""parse_region_rank_item / parse_video_item 字段映射单元测试。

纯函数测试,无网络依赖:
- 搜索 API 字段(typeid 字符串、pubdate 时间戳、tag 逗号字符串、duration 'm:ss')
- popular feed 字段(stat 嵌套、owner 嵌套、pubdate 整数)
- 时长解析、时间转换、分区回退
"""
import time
from collectors.bilibili import (
    parse_region_rank_item,
    parse_video_item,
    KICHU_TIDS,
    CN_TZ,
)
from datetime import datetime


def test_author_avatar_survives_feed_and_search_parsing():
    feed = parse_video_item({'bvid': 'BVavatar', 'owner': {'face': '//i0.hdslb.com/face.jpg'}})
    assert feed['author_avatar'] == 'https://i0.hdslb.com/face.jpg'
    search = parse_region_rank_item(_search_api_video(upic='//i1.hdslb.com/search.jpg'))
    assert search['author_avatar'] == 'https://i1.hdslb.com/search.jpg'


def test_detail_metadata_enrichment_preserves_existing_values_when_missing():
    from collectors.bilibili import _apply_video_metadata
    video = {'author_avatar': 'https://i0.hdslb.com/old.jpg', 'pub_date': 1700000000, 'tname': '鬼畜剧场'}
    _apply_video_metadata(video, {'owner': None, 'pubdate': 0, 'tname': ''})
    assert video == {'author_avatar': 'https://i0.hdslb.com/old.jpg', 'pub_date': 1700000000, 'tname': '鬼畜剧场'}
    _apply_video_metadata(video, {'owner': {'face': '//i0.hdslb.com/new.jpg'}, 'pubdate': 1700000001, 'tname': '鬼畜调教'})
    assert video == {'author_avatar': 'https://i0.hdslb.com/new.jpg', 'pub_date': 1700000001, 'tname': '鬼畜调教'}


# ────────────── parse_region_rank_item ──────────────

def _search_api_video(**overrides):
    """构造搜索 API 返回的 video dict(typeid 为字符串、pubdate 为 Unix 时间戳)"""
    base = {
        'bvid': 'BV1xx411c7mD',
        'aid': 123456,
        'title': '测试<em class="keyword">鬼畜</em>视频',
        'author': '测试UP主',
        'mid': 123,
        'pic': '//i0.hdslb.com/bfs/archive/test.jpg',
        'description': '描述<em class="keyword">文字</em>',
        'typename': '鬼畜调教',
        'typeid': '22',           # 搜索 API 返回字符串
        'play': 100000,
        'video_review': 500,
        'review': 200,
        'favorites': 1000,
        'coins': 800,
        'pts': 95,
        'duration': '3:45',
        'pubdate': 1700000000,     # Unix 时间戳
        'tag': '鬼畜,空耳,哈基米',
    }
    base.update(overrides)
    return base


def test_parse_region_rank_item_basic_fields():
    """搜索 API 正常数据:核心字段正确提取"""
    v = parse_region_rank_item(_search_api_video(), tid=22)
    assert v['bvid'] == 'BV1xx411c7mD'
    assert v['aid'] == 123456
    assert v['author'] == '测试UP主'
    assert v['mid'] == 123
    assert v['views'] == 100000
    assert v['coins'] == 800
    assert v['favorites'] == 1000
    assert v['pts'] == 95


def test_parse_region_rank_item_title_em_stripped():
    """title 中的 <em> 高亮标签应被去除"""
    v = parse_region_rank_item(_search_api_video(), tid=22)
    assert '<em' not in v['title']
    assert '鬼畜' in v['title']


def test_parse_region_rank_item_cover_normalized():
    """// 开头的协议相对 URL 应补全为 https:"""
    v = parse_region_rank_item(_search_api_video(), tid=22)
    assert v['cover'] == 'https://i0.hdslb.com/bfs/archive/test.jpg'


def test_parse_region_rank_item_typeid_string_to_int():
    """搜索 API typeid 是字符串,应转为 int 并作为 real_tid(优先于传入 tid)"""
    v = parse_region_rank_item(_search_api_video(typeid='126'), tid=22)
    assert v['tid'] == 126  # typeid 优先,不被传入 tid 覆盖


def test_parse_region_rank_item_typeid_missing_returns_zero():
    """typeid/tid 都缺失时返回 0(不回退传入 tid,避免分区未知视频伪装成目标分区)。
    设计依据:get_kichu_videos 防御性过滤会丢弃 tid=0 的视频(宁可错杀不漏)。
    """
    v = parse_region_rank_item(_search_api_video(typeid=None), tid=216)
    assert v['tid'] == 0  # 不用传入 tid=216 作 fallback


def test_parse_region_rank_item_pubdate_timestamp():
    """pubdate 为 Unix 时间戳时直接使用"""
    v = parse_region_rank_item(_search_api_video(pubdate=1700000000), tid=22)
    assert v['pub_date'] == 1700000000


def test_parse_region_rank_item_pubdate_create_string():
    """pubdate 缺失时从 create 字符串解析(北京时间)"""
    # 2025-03-31 17:00 北京时间 = 1743402000
    expected = int(datetime(2025, 3, 31, 17, 0, tzinfo=CN_TZ).timestamp())
    v = parse_region_rank_item(
        _search_api_video(pubdate=0, create='2025-03-31 17:00'), tid=22)
    assert v['pub_date'] == expected


def test_parse_region_rank_item_pubdate_create_string_with_seconds():
    """create 字符串带秒数也应解析"""
    expected = int(datetime(2025, 3, 31, 17, 0, 0, tzinfo=CN_TZ).timestamp())
    v = parse_region_rank_item(
        _search_api_video(pubdate=0, create='2025-03-31 17:00:00'), tid=22)
    assert v['pub_date'] == expected


def test_parse_region_rank_item_duration_2segments():
    """duration 'm:ss' 格式解析为秒"""
    v = parse_region_rank_item(_search_api_video(duration='3:45'), tid=22)
    assert v['duration'] == 225  # 3*60+45


def test_parse_region_rank_item_duration_3segments():
    """duration 'h:m:ss' 格式解析为秒"""
    v = parse_region_rank_item(_search_api_video(duration='1:02:03'), tid=22)
    assert v['duration'] == 3723  # 1*3600+2*60+3


def test_parse_region_rank_item_tags_from_search_string():
    """搜索 API tag 是逗号字符串,应拆分为列表(不触发网络)"""
    v = parse_region_rank_item(_search_api_video(tag='鬼畜,空耳,哈基米'), tid=22)
    assert v['tags'] == ['鬼畜', '空耳', '哈基米']


def test_parse_region_rank_item_engagement_estimated():
    """排行榜/搜索 API 不返回 likes/shares,应按 5%/1% 估算"""
    v = parse_region_rank_item(_search_api_video(play=100000), tid=22)
    assert v['likes'] == 5000    # 5%
    assert v['shares'] == 1000   # 1%
    assert v['_stats_estimated'] is True


def test_parse_region_rank_item_url_built():
    """url 应拼为 bilibili 视频页"""
    v = parse_region_rank_item(_search_api_video(), tid=22)
    assert v['url'] == 'https://www.bilibili.com/video/BV1xx411c7mD'


# ────────────── parse_video_item ──────────────

def _popular_feed_video(**overrides):
    """构造 popular feed / ranking API 返回的 video dict(stat/owner 嵌套)"""
    base = {
        'bvid': 'BV1yy411c7xY',
        'aid': 654321,
        'title': '热门视频',
        'description': '热门描述',
        'pic': 'https://i0.hdslb.com/bfs/archive/hot.jpg',
        'tid': 22,
        'tname': '鬼畜调教',
        'duration': 240,
        'pubdate': 1700100000,
        'stat': {
            'view': 200000,
            'danmaku': 800,
            'reply': 300,
            'like': 12000,
            'coin': 1500,
            'favorite': 3000,
            'share': 600,
        },
        'owner': {
            'name': '热门UP',
            'mid': 456,
        },
    }
    base.update(overrides)
    return base


def test_parse_video_item_basic_fields():
    """popular feed 正常数据:核心字段从 stat/owner 嵌套提取"""
    v = parse_video_item(_popular_feed_video(), with_tags=False)
    assert v['bvid'] == 'BV1yy411c7xY'
    assert v['views'] == 200000
    assert v['likes'] == 12000
    assert v['coins'] == 1500
    assert v['favorites'] == 3000
    assert v['shares'] == 600
    assert v['comments'] == 300
    assert v['danmaku'] == 800


def test_parse_video_item_owner_nested():
    """author/mid 从 owner 嵌套提取"""
    v = parse_video_item(_popular_feed_video(), with_tags=False)
    assert v['author'] == '热门UP'
    assert v['mid'] == 456


def test_parse_video_item_duration_int():
    """popular feed duration 是整数,直接使用"""
    v = parse_video_item(_popular_feed_video(duration=240), with_tags=False)
    assert v['duration'] == 240


def test_parse_video_item_pubdate_int():
    """popular feed pubdate 是整数,直接使用"""
    v = parse_video_item(_popular_feed_video(pubdate=1700100000), with_tags=False)
    assert v['pub_date'] == 1700100000


def test_parse_video_item_tid_from_tid_field():
    """popular feed tid 字段优先"""
    v = parse_video_item(_popular_feed_video(tid=216), with_tags=False)
    assert v['tid'] == 216


def test_parse_video_item_tid_fallback_to_typeid():
    """tid 缺失时回退到 typeid"""
    v = parse_video_item(_popular_feed_video(tid=None, typeid=26), with_tags=False)
    assert v['tid'] == 26


def test_parse_video_item_no_estimated_flag():
    """popular feed 有真实 stat,不应标记 _stats_estimated"""
    v = parse_video_item(_popular_feed_video(), with_tags=False)
    assert '_stats_estimated' not in v


def test_parse_video_item_url_built():
    v = parse_video_item(_popular_feed_video(), with_tags=False)
    assert v['url'] == 'https://www.bilibili.com/video/BV1yy411c7xY'


def test_parse_video_item_owner_fallback_to_author():
    """owner 缺失时 author 回退到顶层 author 字段"""
    v = parse_video_item(
        _popular_feed_video(owner=None, author='顶层UP'), with_tags=False)
    assert v['author'] == '顶层UP'


# ────────────── 缺失字段容错 ──────────────

def test_parse_region_rank_item_empty_dict():
    """空 dict 不崩溃,返回字段为默认值"""
    v = parse_region_rank_item({}, tid=22)
    assert v['bvid'] == ''
    assert v['views'] == 0
    assert v['pub_date'] == 0
    assert v['tags'] == [] or v['tags'] is None  # 无 bvid 时不 fetch tags


def test_parse_video_item_empty_dict():
    v = parse_video_item({}, with_tags=False)
    assert v['bvid'] == ''
    assert v['views'] == 0
    assert v['pub_date'] == 0


if __name__ == '__main__':
    import pytest
    pytest.main([__file__, '-v'])
