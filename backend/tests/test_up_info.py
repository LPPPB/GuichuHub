"""get_up_info_by_mid 单元测试。

测试 bilibili_user.py 中的 UP 主详情接口调用:
- 成功响应: 字段映射正确（name/face/sign/level/official_*）
- face http→https 强制转换
- 失败降级: None / error dict / 空数据 均返回 None
- 字段缺失不崩溃

mock safe_get_with_wbi,无真实网络依赖。
"""
import pytest

from collectors.bilibili_user import get_up_info_by_mid


def _acc_info_data(**overrides):
    """构造 /x/space/wbi/acc/info 成功响应"""
    base = {
        'code': 0,
        'data': {
            'mid': 3546915599813120,
            'name': '交叉卷积核',
            'face': 'https://i2.hdslb.com/bfs/face/abc.jpg',
            'sign': '做一个有趣的UP主',
            'level': 5,
            'sex': '男',
            'official': {
                'role': 7,
                'title': '鬼畜区知名UP主',
                'desc': '',
                'type': -1,
            },
            'jointime': 1488297600,
        }
    }
    base['data'].update(overrides)
    return base


def test_get_up_info_by_mid_success(monkeypatch):
    """成功响应: 字段映射正确"""
    monkeypatch.setattr(
        'collectors.bilibili_user.safe_get_with_wbi',
        lambda url, params, max_retries=1: _acc_info_data()
    )
    info = get_up_info_by_mid(3546915599813120)
    assert info is not None
    assert info['mid'] == 3546915599813120
    assert info['name'] == '交叉卷积核'
    assert info['face'] == 'https://i2.hdslb.com/bfs/face/abc.jpg'
    assert info['sign'] == '做一个有趣的UP主'
    assert info['level'] == 5
    assert info['sex'] == '男'
    assert info['official_title'] == '鬼畜区知名UP主'
    assert info['official_type'] == -1
    assert info['jointime'] == 1488297600


def test_get_up_info_by_mid_http_face_https(monkeypatch):
    """face 的 http:// 被替换为 https://"""
    data = _acc_info_data(face='http://i0.hdslb.com/bfs/face/old.jpg')
    monkeypatch.setattr(
        'collectors.bilibili_user.safe_get_with_wbi',
        lambda url, params, max_retries=1: data
    )
    info = get_up_info_by_mid(123)
    assert info['face'] == 'https://i0.hdslb.com/bfs/face/old.jpg'


def test_get_up_info_by_mid_failure_returns_none(monkeypatch):
    """safe_get_with_wbi 返回 None → get_up_info_by_mid 返回 None"""
    monkeypatch.setattr(
        'collectors.bilibili_user.safe_get_with_wbi',
        lambda url, params, max_retries=1: None
    )
    assert get_up_info_by_mid(123) is None


def test_get_up_info_by_mid_error_response(monkeypatch):
    """error dict（Cookie过期等）→ 返回 None"""
    monkeypatch.setattr(
        'collectors.bilibili_user.safe_get_with_wbi',
        lambda url, params, max_retries=1: {'error': 'cookie_expired', 'message': '过期'}
    )
    assert get_up_info_by_mid(123) is None


def test_get_up_info_by_mid_missing_fields_no_crash(monkeypatch):
    """data 为空 dict 时不崩溃，返回 None"""
    monkeypatch.setattr(
        'collectors.bilibili_user.safe_get_with_wbi',
        lambda url, params, max_retries=1: {'code': 0, 'data': {}}
    )
    assert get_up_info_by_mid(123) is None


def test_get_up_info_by_mid_missing_official_no_crash(monkeypatch):
    """official 字段缺失时不崩溃，official_title/official_type 取默认值"""
    data = _acc_info_data()
    del data['data']['official']
    monkeypatch.setattr(
        'collectors.bilibili_user.safe_get_with_wbi',
        lambda url, params, max_retries=1: data
    )
    info = get_up_info_by_mid(123)
    assert info is not None
    assert info['official_title'] == ''
    assert info['official_type'] == -1


def test_get_up_info_by_mid_uses_correct_url(monkeypatch):
    """验证调用的是 /x/space/wbi/acc/info 接口"""
    captured = {}

    def fake_safe_get(url, params, max_retries=1):
        captured['url'] = url
        captured['params'] = params
        return _acc_info_data()

    monkeypatch.setattr('collectors.bilibili_user.safe_get_with_wbi', fake_safe_get)
    get_up_info_by_mid(456)
    assert captured['url'] == 'https://api.bilibili.com/x/space/wbi/acc/info'
    assert captured['params'] == {'mid': 456}
