"""神评论精选 get_golden_comments 单元测试。

用 monkeypatch mock 网络层(fetch_comments),验证:
- 官方热门识别(attr bit27 位标记)与 UP主点赞(up_action.like)
- 综合评分排序(官方热评/UP主点赞优先, 非纯点赞)
- 过滤(无文本/过短/低赞)
- 每视频精选 TOP2 覆盖
- 跨视频去重
不依赖真实网络。
"""

import pytest
from collectors.bilibili import get_golden_comments


def _reply(message, like=100, rcount=5, attr=0, up_like=False, ctime=1784211203,
           uname='路人', avatar='', level=4, location='IP属地：江苏', emotes=None, rpid=123456):
    """构造评论 API 的 reply dict"""
    return {
        'content': {'message': message, 'emote': emotes or {}},
        'like': like,
        'rcount': rcount,
        'attr': attr,
        'ctime': ctime,
        'rpid': rpid,
        'up_action': {'like': up_like},
        'reply_control': {'location': location},
        'member': {
            'uname': uname,
            'mid': 12345,
            'avatar': avatar,
            'level_info': {'current_level': level},
        },
    }


def _video(bvid, title='测试视频', aid=1):
    return {'aid': aid, 'bvid': bvid, 'title': title, 'cover': '//i0.hdslb.com/test.jpg'}


# ── 官方热门识别 ──

def test_is_hot_attr_bit27(monkeypatch):
    """attr 位标记 bit27(0x8000000) = 官方热门"""
    replies = [
        _reply('普通评论', like=10, attr=0),
        _reply('热门评论', like=50, attr=0x8000000),
    ]
    monkeypatch.setattr('collectors.bilibili.fetch_comments', lambda *a, **k: replies)
    result = get_golden_comments([_video('BV1')])
    assert result
    assert result[0]['content'] == '热门评论'
    assert result[0]['is_hot'] is True


def test_up_liked_flag(monkeypatch):
    """up_action.like = UP主觉得很赞"""
    replies = [
        _reply('UP主点赞的评论', like=10, up_like=True),
        _reply('更高赞但没被UP主点赞', like=200, up_like=False),
    ]
    monkeypatch.setattr('collectors.bilibili.fetch_comments', lambda *a, **k: replies)
    result = get_golden_comments([_video('BV1')])
    # UP主点赞优先于纯高赞
    assert result[0]['content'] == 'UP主点赞的评论'
    assert result[0]['up_liked'] is True


# ── 过滤规则 ──

def test_filter_short_and_no_text(monkeypatch):
    """无文本/过短/低赞评论被过滤"""
    replies = [
        _reply('', like=999),           # 纯图片评论（无文本）
        _reply('短', like=999),          # 过短（<4字符）
        _reply('低赞评论', like=2),      # 低赞（<3）
        _reply('有效评论内容', like=50), # 合法
    ]
    monkeypatch.setattr('collectors.bilibili.fetch_comments', lambda *a, **k: replies)
    result = get_golden_comments([_video('BV1')])
    assert len(result) == 1
    assert result[0]['content'] == '有效评论内容'


# ── 综合评分排序 ──

def test_scoring_not_pure_like(monkeypatch):
    """综合评分：回复数×3 计入，官方热门×500 加成"""
    replies = [
        _reply('高赞但无回复', like=300, rcount=0),
        _reply('低赞但高回复', like=50, rcount=100),
    ]
    monkeypatch.setattr('collectors.bilibili.fetch_comments', lambda *a, **k: replies)
    result = get_golden_comments([_video('BV1')])
    # 50 + 100*3 = 350 > 300，高回复评论应排前
    assert result[0]['content'] == '低赞但高回复'


# ── 每视频 TOP2 覆盖 ──

def test_top2_per_video(monkeypatch):
    """每个视频只精选 TOP2，来源覆盖更广"""
    videos = [_video(f'BV{i}', f'视频{i}', aid=i + 1) for i in range(3)]
    # 每个视频的评论内容不同（避免跨视频去重合并）
    def fake_fetch(aid, **kwargs):
        idx = int(aid)
        return [_reply(f'视频{idx}评论内容{i}', like=100 + i) for i in range(10)]
    monkeypatch.setattr('collectors.bilibili.fetch_comments', fake_fetch)
    result = get_golden_comments(videos)
    # 3 个视频 × 每视频 2 条 = 6 条
    assert len(result) == 6
    assert len({c['source_bvid'] for c in result}) == 3


# ── 跨视频去重 ──

def test_dedup_same_author_content(monkeypatch):
    """同一作者同一内容跨视频只保留一条"""
    replies = [_reply('重复评论', like=100)]
    monkeypatch.setattr('collectors.bilibili.fetch_comments', lambda *a, **k: replies)
    result = get_golden_comments([_video('BV1'), _video('BV2')])
    assert len(result) == 1


# ── 表情/头像/等级/IP属地提取 ──

def test_metadata_extraction(monkeypatch):
    """表情映射/头像/等级/IP属地 字段提取"""
    replies = [
        _reply('太搞笑了[吃瓜]', like=100, avatar='https://i1.hdslb.com/face.jpg',
               level=6, location='IP属地：浙江',
               emotes={'[吃瓜]': {'url': 'https://i0.hdslb.com/emote.png'}}),
    ]
    monkeypatch.setattr('collectors.bilibili.fetch_comments', lambda *a, **k: replies)
    result = get_golden_comments([_video('BV1')])
    assert result[0]['emotes'] == {'[吃瓜]': 'https://i0.hdslb.com/emote.png'}
    assert result[0]['author_avatar'] == 'https://i1.hdslb.com/face.jpg'
    assert result[0]['author_level'] == 6
    assert result[0]['location'] == 'IP属地：浙江'


# ── 空数据 ──

def test_empty_replies(monkeypatch):
    """无评论时不崩溃，返回空列表"""
    monkeypatch.setattr('collectors.bilibili.fetch_comments', lambda *a, **k: [])
    assert get_golden_comments([_video('BV1')]) == []


def test_missing_aid(monkeypatch):
    """无 aid 的视频跳过"""
    calls = []
    def fake_fetch(aid, **kwargs):
        calls.append(aid)
        return []
    monkeypatch.setattr('collectors.bilibili.fetch_comments', fake_fetch)
    get_golden_comments([{'bvid': 'BV1', 'title': '无aid视频'}])
    assert calls == []


# ── 评论 rpid 保留（前端跳转定位到具体评论） ──

def test_rpid_preserved(monkeypatch):
    """评论必须保留 rpid，供前端拼接 #reply{rpid} 跳转定位到该评论"""
    replies = [_reply('保留评论ID', like=100, rpid=987654321)]
    monkeypatch.setattr('collectors.bilibili.fetch_comments', lambda *a, **k: replies)
    result = get_golden_comments([_video('BV1')])
    assert result[0]['rpid'] == 987654321
