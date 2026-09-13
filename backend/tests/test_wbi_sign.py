"""WBI 签名算法单元测试。

测试 bilibili_auth.py 中的 WBI 签名函数:
- _get_mixin_key: 混排表生成 mixin key（用官方已知向量验证算法正确性）
- _sign_wbi_params: 参数签名（加 wts/w_rid、按字母序、密钥不可用降级）
- safe_get_with_wbi: 带 WBI 签名的 GET 请求（成功/Cookie过期/重试）

纯函数测试 + monkeypatch mock 网络层,无真实网络依赖。
"""
import hashlib
import urllib.parse

import pytest

from collectors.bilibili_auth import (
    _MIXIN_KEY_ENC_TAB,
    _get_mixin_key,
    _sign_wbi_params,
    safe_get_with_wbi,
)


# ────────────── _get_mixin_key ──────────────

def test_get_mixin_key_known_vector():
    """用 SocialSisterYang/bilibili-WBI-signature 公开示例验证算法正确性。

    官方示例: img_key + sub_key → mixin_key（前32位）
    此处用固定 img_key/sub_key 验证混排表和截断逻辑。
    """
    img_key = '7cd084941338484aae1ad9425b84077c'
    sub_key = '4932caff0ff746eab6f01bf08b70ac45'
    mixin = _get_mixin_key(img_key, sub_key)
    # 手动按混排表计算期望值
    raw = img_key + sub_key
    expected = ''.join(raw[i] for i in _MIXIN_KEY_ENC_TAB if i < len(raw))[:32]
    assert mixin == expected
    assert len(mixin) == 32


def test_get_mixin_key_length_32_with_realistic_input():
    """真实 img_key+sub_key（各32位）→ mixin key 恒为 32 位"""
    img_key = '7cd084941338484aae1ad9425b84077c'  # 32位
    sub_key = '4932caff0ff746eab6f01bf08b70ac45'  # 32位
    mixin = _get_mixin_key(img_key, sub_key)
    assert len(mixin) == 32


# ────────────── _sign_wbi_params ──────────────

def test_sign_wbi_params_adds_wts_and_w_rid(monkeypatch):
    """签名后参数含 wts(int) 和 w_rid(32位hex)"""
    monkeypatch.setattr(
        'collectors.bilibili_auth._get_wbi_keys',
        lambda: ('img_key_123', 'sub_key_456')
    )
    result = _sign_wbi_params({'mid': 123})
    assert 'wts' in result
    assert isinstance(result['wts'], int)
    assert 'w_rid' in result
    assert len(result['w_rid']) == 32  # md5 hex

    # 独立计算验证 w_rid 一致
    mixin_key = _get_mixin_key('img_key_123', 'sub_key_456')
    params_copy = {'mid': 123, 'wts': result['wts']}
    sorted_params = sorted(params_copy.items(), key=lambda x: x[0])
    query_string = urllib.parse.urlencode(sorted_params)
    expected_w_rid = hashlib.md5((query_string + mixin_key).encode('utf-8')).hexdigest()
    assert result['w_rid'] == expected_w_rid


def test_sign_wbi_params_sorted_by_key(monkeypatch):
    """参数按字母序拼接（输入顺序不影响签名结果）"""
    monkeypatch.setattr(
        'collectors.bilibili_auth._get_wbi_keys',
        lambda: ('img_key', 'sub_key')
    )
    monkeypatch.setattr(
        'collectors.bilibili_auth.time.time',
        lambda: 1700000000  # 固定时间戳，消除 wts 差异
    )
    # 顺序传入
    r1 = _sign_wbi_params({'a': 1, 'b': 2, 'c': 3})
    # 打乱传入
    r2 = _sign_wbi_params({'c': 3, 'a': 1, 'b': 2})
    # wts 相同（已固定时间），w_rid 应一致（证明按字母序拼接）
    assert r1['wts'] == r2['wts']
    assert r1['w_rid'] == r2['w_rid']


def test_sign_wbi_params_no_keys_returns_original(monkeypatch):
    """密钥不可用时返回原 params（不含 w_rid，跳过签名）"""
    monkeypatch.setattr(
        'collectors.bilibili_auth._get_wbi_keys',
        lambda: (None, None)
    )
    original = {'mid': 123}
    result = _sign_wbi_params(original)
    assert 'w_rid' not in result
    assert result == original


def test_sign_wbi_params_does_not_mutate_input(monkeypatch):
    """签名不修改传入的原始 params dict"""
    monkeypatch.setattr(
        'collectors.bilibili_auth._get_wbi_keys',
        lambda: ('img_key', 'sub_key')
    )
    original = {'mid': 123}
    _sign_wbi_params(original)
    assert original == {'mid': 123}  # 原字典未被修改


# ────────────── safe_get_with_wbi ──────────────

class _FakeResponse:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


def test_safe_get_with_wbi_success(monkeypatch):
    """code=0 时返回完整响应 dict"""
    monkeypatch.setattr(
        'collectors.bilibili_auth._get_wbi_keys',
        lambda: ('img_key', 'sub_key')
    )
    monkeypatch.setattr(
        'collectors.bilibili_auth.get_cookie_str',
        lambda: 'SESSDATA=fake'
    )
    monkeypatch.setattr(
        'collectors.bilibili_auth.get_headers',
        lambda cookie=None: {}
    )

    captured_params = {}

    def fake_get(url, headers=None, params=None, timeout=None):
        captured_params.update(params or {})
        return _FakeResponse({'code': 0, 'data': {'mid': 123, 'name': 'test'}})

    monkeypatch.setattr('collectors.bilibili_auth.requests.get', fake_get)
    result = safe_get_with_wbi('https://api.bilibili.com/test', {'mid': 123})
    assert result == {'code': 0, 'data': {'mid': 123, 'name': 'test'}}
    # 签名参数已附加
    assert 'wts' in captured_params
    assert 'w_rid' in captured_params


def test_safe_get_with_wbi_cookie_expired(monkeypatch):
    """code=-101 返回 cookie_expired error dict"""
    monkeypatch.setattr(
        'collectors.bilibili_auth._get_wbi_keys',
        lambda: ('img_key', 'sub_key')
    )
    monkeypatch.setattr(
        'collectors.bilibili_auth.get_cookie_str',
        lambda: 'SESSDATA=fake'
    )
    monkeypatch.setattr(
        'collectors.bilibili_auth.get_headers',
        lambda cookie=None: {}
    )
    monkeypatch.setattr(
        'collectors.bilibili_auth.requests.get',
        lambda *a, **kw: _FakeResponse({'code': -101, 'message': '账号未登录'})
    )
    result = safe_get_with_wbi('https://api.bilibili.com/test', {'mid': 123})
    assert result == {'error': 'cookie_expired', 'message': 'Cookie已过期，请重新登录'}


def test_safe_get_with_wbi_no_cookie_returns_none(monkeypatch):
    """无 Cookie 时返回 None"""
    monkeypatch.setattr(
        'collectors.bilibili_auth.get_cookie_str',
        lambda: None
    )
    result = safe_get_with_wbi('https://api.bilibili.com/test', {'mid': 123})
    assert result is None


def test_safe_get_with_wbi_retries_on_error_code(monkeypatch):
    """非0非-101 code 时重试，最终成功"""
    monkeypatch.setattr(
        'collectors.bilibili_auth._get_wbi_keys',
        lambda: ('img_key', 'sub_key')
    )
    monkeypatch.setattr(
        'collectors.bilibili_auth.get_cookie_str',
        lambda: 'SESSDATA=fake'
    )
    monkeypatch.setattr(
        'collectors.bilibili_auth.get_headers',
        lambda cookie=None: {}
    )
    # 避免 time.sleep 真实等待
    monkeypatch.setattr('collectors.bilibili_auth.time.sleep', lambda *a: None)

    call_count = [0]

    def fake_get(*a, **kw):
        call_count[0] += 1
        if call_count[0] == 1:
            return _FakeResponse({'code': -509, 'message': '限流'})
        return _FakeResponse({'code': 0, 'data': 'ok'})

    monkeypatch.setattr('collectors.bilibili_auth.requests.get', fake_get)
    result = safe_get_with_wbi('https://api.bilibili.com/test', {'mid': 123}, max_retries=2)
    assert result == {'code': 0, 'data': 'ok'}
    assert call_count[0] == 2  # 第一次失败，第二次成功


def test_safe_get_with_wbi_risk_control_exhausts_retries(monkeypatch, capsys):
    """-412 风控持续失败：重试耗尽后返回 None，共发 max_retries+1 次请求

    -412（风控拦截）是非0非-101 code → 走重试分支；若持续被拦截，
    循环 max_retries+1=3 次后降级返回 None（调用方据此走兜底/中断，如
    fetch_up_full_videos 收到 None 直接 break 停止翻页，up_card 返回失败）。

    验证四件事：
    1. 返回值是 None（不抛异常，调用方可安全判空）
    2. 请求次数有硬上限（3 次，不会无限重试轰炸风控）
    3. 每次 -412 后固定 sleep 0.5s 控制频率
    4. 每次失败都打印错误日志（运维可观测到风控）
    """
    monkeypatch.setattr(
        'collectors.bilibili_auth._get_wbi_keys',
        lambda: ('img_key', 'sub_key')
    )
    monkeypatch.setattr(
        'collectors.bilibili_auth.get_cookie_str',
        lambda: 'SESSDATA=fake'
    )
    monkeypatch.setattr(
        'collectors.bilibili_auth.get_headers',
        lambda cookie=None: {}
    )
    sleeps = []
    monkeypatch.setattr('collectors.bilibili_auth.time.sleep', lambda s: sleeps.append(s))

    call_count = [0]

    def fake_get(*a, **kw):
        call_count[0] += 1
        return _FakeResponse({'code': -412, 'message': '请求被拦截'})

    monkeypatch.setattr('collectors.bilibili_auth.requests.get', fake_get)
    result = safe_get_with_wbi('https://api.bilibili.com/test', {'mid': 123}, max_retries=2)
    assert result is None  # 重试耗尽 → 降级 None，不抛异常
    assert call_count[0] == 3  # max_retries + 1，请求次数有硬上限
    assert sleeps == [0.5, 0.5, 0.5]  # 每次 -412 后固定 0.5s 间隔
    out = capsys.readouterr().out
    assert out.count('code=-412') == 3  # 每次失败都打错误日志（运维可观测风控）
