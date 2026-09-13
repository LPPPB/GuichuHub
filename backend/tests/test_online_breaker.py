# -*- coding: utf-8 -*-
"""同接抓取熔断（L3 降级）单元测试。

验证：连续失败自动熔断 → 停止发起同接请求 → 冷却到期半开探测 →
连续成功达配额才恢复闭合（渐进式，防恢复-再熔断抖动）；任一次探测失败立即重熔；
-412 风控错误立即熔断；熔断期 _enrich_with_stats 不再请求同接（历史平滑回退）。
"""
import time

import pytest

from collectors import bilibili as b


@pytest.fixture(autouse=True)
def _no_alert_side_effect(monkeypatch):
    """隔离邮件告警：熔断测试不关心告警，且不应依赖运行环境是否配置 SMTP
    （本地 .env 配了 SMTP 时 _breaker_event 会真实发邮件并污染 alerter._sent_flags）"""
    from utils import alerter
    monkeypatch.setattr(alerter, 'send_breaker_alert', lambda *a, **k: False)
    monkeypatch.setattr(alerter, 'reset_breaker_alert', lambda: None)


def _reset():
    b._ONLINE_BREAKER.update({'fails': 0, 'open_ts': 0, 'probes': 0, 'probe_ok': 0})
    b._ONLINE_BREAKER_TREND.clear()


def test_breaker_opens_after_3_fails():
    """连续 3 次失败 → 熔断打开；冷却未到期期间保持打开。"""
    _reset()
    b._online_breaker_record(False)
    b._online_breaker_record(False)
    assert not b._online_breaker_open(), '累计 2 次失败不应熔断'
    b._online_breaker_record(False)  # 第 3 次 → 打开
    assert b._online_breaker_open()
    # 冷却未到期（open_ts 是刚才）→ 仍打开
    assert b._online_breaker_open()
    _reset()


def test_breaker_412_blocked_immediate():
    """-412 风控错误不计累计、立即熔断。"""
    _reset()
    b._online_breaker_record(False, blocked=True)
    assert b._online_breaker_open(), '-412 应立即熔断'
    _reset()


def test_breaker_recovers_after_cooldown():
    """冷却到期转半开：放行探测，连续 3 次成功达配额才恢复闭合（渐进式）。"""
    _reset()
    b._ONLINE_BREAKER.update({'fails': 3, 'open_ts': time.time() - 9999})
    assert not b._online_breaker_open(), '冷却过期应放行半开探测'
    # 第 1、2 次成功：仍未达配额，保持半开继续放行探测
    b._online_breaker_record(True)
    assert b._ONLINE_BREAKER['fails'] == 3, '半开未达配额前不得恢复闭合'
    assert b._ONLINE_BREAKER['probe_ok'] == 1
    assert not b._online_breaker_open(), '半开探测配额未用尽，继续放行'
    b._online_breaker_record(True)
    assert b._ONLINE_BREAKER['probe_ok'] == 2
    # 第 3 次成功：达配额 → 恢复闭合并清零
    b._online_breaker_record(True)
    assert b._ONLINE_BREAKER['fails'] == 0
    assert b._ONLINE_BREAKER['probe_ok'] == 0
    assert not b._online_breaker_open()
    _reset()


def test_breaker_half_open_probe_fail_reopens():
    """半开探测失败 → 立即重熔，刷新冷却并清空半开计数。"""
    _reset()
    b._ONLINE_BREAKER.update({'fails': 3, 'open_ts': time.time() - 9999})
    b._online_breaker_record(False)  # 探测失败
    assert b._online_breaker_open(), '探测失败应重新熔断'
    assert b._ONLINE_BREAKER['fails'] >= b.ONLINE_BREAK_THRESHOLD
    assert b._ONLINE_BREAKER['probes'] == 0, '重熔应清空半开计数'
    _reset()


def test_half_open_quota_exhausted_blocks():
    """半开配额用尽仍未恢复（防呆路径）：按打开处理，调用方跳过同接请求。"""
    _reset()
    b._ONLINE_BREAKER.update(
        {'fails': 3, 'open_ts': time.time() - 9999, 'probes': 3, 'probe_ok': 2})
    assert b._online_breaker_open(), '配额用尽应视为打开'
    _reset()


def test_breaker_trend_records_state_changes():
    """熔断状态变化记录进趋势环形缓冲，供 /api/status 趋势图展示。"""
    _reset()
    b._online_breaker_record(False)
    b._online_breaker_record(False)
    b._online_breaker_record(False)  # 第 3 次失败 → open
    assert len(b._ONLINE_BREAKER_TREND) == 1
    assert b._ONLINE_BREAKER_TREND[-1]['state'] == 'open'
    assert b._ONLINE_BREAKER_TREND[-1]['fails'] == 3
    # 冷却过期 → 半开连续 3 次成功 → closed
    b._ONLINE_BREAKER.update({'open_ts': time.time() - 9999})
    b._online_breaker_record(True)
    b._online_breaker_record(True)
    b._online_breaker_record(True)
    assert b._ONLINE_BREAKER_TREND[-1]['state'] == 'closed'
    assert b._ONLINE_BREAKER_TREND[-1]['fails'] == 0
    assert [p['state'] for p in b.get_online_breaker_trend()] == ['open', 'closed']
    _reset()


def test_breaker_trend_ring_buffer_cap():
    """趋势环形缓冲有上限（防内存无限增长），超限裁剪最旧记录。"""
    _reset()
    for i in range(b._ONLINE_BREAKER_TREND_MAX + 20):
        b._breaker_trend_record('open', i % 7)  # 用 fails 值标记记录序号，验证裁剪顺序
    assert len(b._ONLINE_BREAKER_TREND) == b._ONLINE_BREAKER_TREND_MAX
    assert b._ONLINE_BREAKER_TREND[0]['fails'] == (20 % 7), '应裁剪最旧的 20 条，剩余首条为第 20 条记录'
    assert len(b.get_online_breaker_trend()) == 50, 'API 默认只返回最近 50 条'
    _reset()


def test_fetch_online_count_success_resets_breaker(monkeypatch):
    """同接请求成功 → 熔断计数清零。"""
    _reset()
    b._ONLINE_BREAKER['fails'] = 2
    monkeypatch.setattr(b, 'safe_get', lambda url, params=None, return_error_code=False: {'code': 0, 'data': {'total': '123'}})
    assert b.fetch_online_count('BV1', cid=1) == (123, 'exact', '123')
    assert b._ONLINE_BREAKER['fails'] == 0
    _reset()


def test_fetch_online_count_1000plus_parsed(monkeypatch):
    """B 站对超 1000 同接返回 "1000+"：按千位下限解析，且计为成功（不误判熔断失败）。

    修复前 int("1000+") 抛 ValueError → 记一次熔断失败，一批多个 1000+ 视频
    会把"正常高并发"误判为"风控拦截"而触发熔断。
    """
    _reset()
    monkeypatch.setattr(b, 'safe_get',
                        lambda url, params=None, return_error_code=False: {'code': 0, 'data': {'total': '1000+'}})
    assert b.fetch_online_count('BV1', cid=1) == (1000, 'k_plus', '1000+')
    assert b._ONLINE_BREAKER['fails'] == 0, '"1000+" 是正常响应，不应计为失败'
    _reset()


def test_fetch_online_count_wan_parsed(monkeypatch):
    r"""B 站超 1 万同接返回 "1.1万"/"1.5万"：按万位显示值解析。

    修复前 re.match(r'^(\d+)') 只取开头数字 → "1.1万" 被解析成 1（低估 1.1 万倍）、
    "1.5万" 解析成 1。该 bug 会让 1 万+ 同接的爆发视频动能被严重低估。
    """
    _reset()
    monkeypatch.setattr(b, 'safe_get',
                        lambda url, params=None, return_error_code=False: {'code': 0, 'data': {'total': '1.1万'}})
    assert b.fetch_online_count('BV1', cid=1) == (11000, 'w', '1.1万')
    _reset()
    monkeypatch.setattr(b, 'safe_get',
                        lambda url, params=None, return_error_code=False: {'code': 0, 'data': {'total': '1.5万'}})
    assert b.fetch_online_count('BV1', cid=1) == (15000, 'w', '1.5万')
    _reset()


def test_parse_online_count_formats():
    """parse_online_count 覆盖 B 站同接全部展示格式：精确/千取整+/万取整/异常。"""
    assert b.parse_online_count(952) == (952, 'exact', '952')
    assert b.parse_online_count('952') == (952, 'exact', '952')
    assert b.parse_online_count(' 123 ') == (123, 'exact', '123')
    assert b.parse_online_count('1000+') == (1000, 'k_plus', '1000+')
    assert b.parse_online_count('2000+') == (2000, 'k_plus', '2000+')
    assert b.parse_online_count('1.1万') == (11000, 'w', '1.1万')
    assert b.parse_online_count('1.5万') == (15000, 'w', '1.5万')
    assert b.parse_online_count('1万') == (10000, 'w', '1万')
    # 异常/未知格式 → 全 None（调用方按"未知"处理，不误判）
    assert b.parse_online_count('') == (None, None, None)
    assert b.parse_online_count(None) == (None, None, None)
    assert b.parse_online_count('abc') == (None, None, None)
    assert b.parse_online_count('1.1万+') == (11000, 'w', '1.1万+')  # 防御 + 后缀


def test_fetch_online_count_412_triggers_breaker(monkeypatch):
    """同接请求返回 -412 → 立即熔断并返回 None。"""
    _reset()
    monkeypatch.setattr(b, 'safe_get', lambda url, params=None, return_error_code=False: {'code': -412, 'message': '风控'})
    assert b.fetch_online_count('BV1', cid=1) == (None, None, None)
    assert b._online_breaker_open()
    _reset()


def test_enrich_skips_online_requests_while_breaker_open(monkeypatch):
    """熔断期间 _enrich_with_stats 不再发起同接请求（raw=None → 平滑回退历史）。"""
    _reset()
    b._ONLINE_BREAKER.update({'fails': 3, 'open_ts': time.time()})
    called = {'n': 0}

    def fake_fetch(*a, **k):
        called['n'] += 1
        return 100

    monkeypatch.setattr(b, 'fetch_online_count', fake_fetch)
    monkeypatch.setattr(b, 'fetch_video_detail', lambda bvid: {'cid': 1, 'stat': {}})
    monkeypatch.setattr(b, '_smooth_online', lambda bvid, cur: cur)

    v = {'bvid': 'BV1', 'views': 1000}
    b._enrich_with_stats([v])

    assert called['n'] == 0, '熔断期间不应发起同接请求'
    assert v.get('online_count_raw') is None
    assert v.get('online_circuit_skipped') is True
    _reset()


def test_enrich_requests_online_when_breaker_closed(monkeypatch):
    """熔断关闭时 _enrich_with_stats 正常请求同接。"""
    _reset()
    monkeypatch.setattr(b, 'fetch_online_count', lambda bvid, cid=None: (88, 'exact', '88'))
    monkeypatch.setattr(b, 'fetch_video_detail', lambda bvid: {'cid': 1, 'stat': {}})
    monkeypatch.setattr(b, '_smooth_online', lambda bvid, cur: cur)

    v = {'bvid': 'BV1', 'views': 1000}
    b._enrich_with_stats([v])

    assert v['online_count_raw'] == 88
    assert not v.get('online_circuit_skipped')
    _reset()


def test_enrich_persists_display_and_precision(monkeypatch):
    """_enrich_with_stats 正确解包三元组：online_display=原始展示、online_precision=精度标记。

    回归：曾把解包顺序写成 (value, display, precision)，而 fetch_online_count 返回
    (value, precision, display) → display 与 precision 互换（"1000+" 被存进 precision）。
    这里用可区分的值验证字段落位。
    """
    _reset()
    monkeypatch.setattr(b, 'fetch_online_count',
                        lambda bvid, cid=None: (1000, 'k_plus', '1000+'))
    monkeypatch.setattr(b, 'fetch_video_detail', lambda bvid: {'cid': 1, 'stat': {}})
    monkeypatch.setattr(b, '_smooth_online', lambda bvid, cur: cur)

    v = {'bvid': 'BV1', 'views': 1000}
    b._enrich_with_stats([v])

    assert v['online_count_raw'] == 1000
    assert v['online_display'] == '1000+', f'display 应为原始展示字符串，实际 {v.get("online_display")!r}'
    assert v['online_precision'] == 'k_plus', f'precision 应为精度标记，实际 {v.get("online_precision")!r}'
    _reset()


def test_412_block_opens_breaker_and_skips_rest(monkeypatch):
    """模拟真实 -412 拦截：首个同接请求被风控拦截 → 立即熔断 → 同批后续视频全部跳过同接请求。

    场景还原：B 站对 online/total 接口返回 code=-412（风控拦截）。
    验证闭环：
      1. 首个视频的 safe_get 请求被 -412 拦截，fetch 返回 None（A2 语义：未知≠0）
      2. 熔断立即打开，同批剩余视频不再发起同接请求（safe_get 只被调用 1 次）
      3. 被跳过的视频打 online_circuit_skipped 标记，raw=None → 平滑回退历史（L2 兜底）

    mock 设计：safe_get 首次返回 -412，若熔断失效后续会返回成功——
    若实现有 bug（未跳过），raw 会拿到 100 而非 None，断言直接暴露。
    """
    _reset()
    calls = {'safe_get': 0, 'online_fetch': 0}

    def fake_safe_get(url, params=None, return_error_code=False):
        """模拟 B 站 online/total 接口：首次调用即被风控 -412 拦截。"""
        calls['safe_get'] += 1
        if calls['safe_get'] == 1:
            return {'code': -412, 'message': '风控拦截'}
        # 熔断若未生效，后续调用会走到这里返回成功（测试应暴露该缺陷）
        return {'code': 0, 'data': {'total': '100'}}

    orig_fetch_online = b.fetch_online_count  # 先存原引用，包装计数后仍走真实实现

    def fake_fetch_online(bvid, cid=None):
        calls['online_fetch'] += 1
        return orig_fetch_online(bvid, cid)

    monkeypatch.setattr(b, 'safe_get', fake_safe_get)
    monkeypatch.setattr(b, 'fetch_online_count', fake_fetch_online)
    monkeypatch.setattr(b, 'fetch_video_detail', lambda bvid: {'cid': 1, 'stat': {}})
    monkeypatch.setattr(b, '_smooth_online', lambda bvid, cur: cur)

    vids = [{'bvid': f'BV{i}', 'views': 1000} for i in range(1, 4)]
    b._enrich_with_stats(vids)

    # ① 同接请求只发生 1 次（首个被拦截），剩余视频被跳过
    assert calls['online_fetch'] == 1, 'fetch_online_count 只应被调用 1 次'
    assert calls['safe_get'] == 1, 'safe_get 只应被调用 1 次（首个请求被 -412 拦截后熔断）'
    # ② 熔断立即打开
    assert b._online_breaker_open(), '-412 应立即熔断'
    # ③ 首个视频：拦截 → raw=None（未知语义）；后续视频：跳过 → raw=None + 熔断标记
    assert vids[0]['online_count_raw'] is None
    assert not vids[0].get('online_circuit_skipped'), '首个视频是真实请求被拦截，非熔断跳过'
    for v in vids[1:]:
        assert v['online_count_raw'] is None, f'{v["bvid"]} 应跳过同接请求（raw=None）'
        assert v.get('online_circuit_skipped') is True, f'{v["bvid"]} 应打熔断跳过标记'
    _reset()


def test_412_block_then_cooldown_recovers(monkeypatch):
    """风控解除（冷却到期）后自动恢复：半开探测连续成功达配额 → 熔断闭合 → 请求恢复正常。

    场景还原：上一轮 -412 已熔断，冷却 1800s 到期后系统自动转半开。
    3 个候选视频恰好占满半开探测配额（HALF_OPEN_LIMIT=3），全部成功后恢复闭合。
    验证闭环：
      1. 半开期所有视频放行探测（不再跳过），全部请求同接
      2. 第 3 个探测成功时达配额 → 熔断计数清零、恢复闭合
      3. 所有视频拿到实测 raw，无熔断标记
    """
    _reset()
    # 预置：已熔断且冷却过期（进入半开探测态）
    b._ONLINE_BREAKER.update({'fails': 3, 'open_ts': time.time() - 9999})
    calls = {'n': 0}

    def fake_safe_get(url, params=None, return_error_code=False):
        """模拟风控解除：online/total 接口恢复正常，返回实测同接 66。"""
        return {'code': 0, 'data': {'total': '66'}}

    orig_fetch_online = b.fetch_online_count  # 走真实实现，验证探测成功会清零计数

    def fake_fetch_online(bvid, cid=None):
        calls['n'] += 1
        return orig_fetch_online(bvid, cid)

    monkeypatch.setattr(b, 'safe_get', fake_safe_get)
    monkeypatch.setattr(b, 'fetch_online_count', fake_fetch_online)
    monkeypatch.setattr(b, 'fetch_video_detail', lambda bvid: {'cid': 1, 'stat': {}})
    monkeypatch.setattr(b, '_smooth_online', lambda bvid, cur: cur)

    vids = [{'bvid': f'BV{i}', 'views': 1000} for i in range(1, 4)]
    b._enrich_with_stats(vids)

    assert calls['n'] == 3, '半开探测成功后应恢复正常请求（3 个视频全部请求同接）'
    assert not b._online_breaker_open(), '探测成功应恢复闭合'
    assert b._ONLINE_BREAKER['fails'] == 0, '成功后失败计数应清零'
    for v in vids:
        assert v['online_count_raw'] == 66
        assert not v.get('online_circuit_skipped')
    _reset()
