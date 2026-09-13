# -*- coding: utf-8 -*-
"""邮件告警（utils/alerter.py）单元测试。

验证：未配置 SMTP 静默跳过（不触碰 smtplib）；open/reopen 告警触发且同周期去重；
恢复闭合（reset）后下一周期可重新告警；SMTP 发送失败被吞掉不影响主流程；
端口 465 走 SMTP_SSL。
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from utils import alerter


def _reset_flags():
    alerter._sent_flags.update({'open': False, 'reopen': False})


def test_unconfigured_smtp_silent(monkeypatch):
    """未配置 SMTP（host/to 为空）→ 静默跳过，不触碰 smtplib。"""
    _reset_flags()
    monkeypatch.setattr(config, 'ALERT_SMTP_HOST', '')
    monkeypatch.setattr(config, 'ALERT_MAIL_TO', '')
    called = {'n': 0}

    class BoomServer:
        def __init__(self, *a, **k):
            called['n'] += 1
            raise AssertionError('未配置 SMTP 不应触碰 smtplib')

    monkeypatch.setattr(alerter.smtplib, 'SMTP_SSL', BoomServer)
    assert alerter.send_breaker_alert('open', 3) is False
    assert called['n'] == 0
    _reset_flags()


def test_open_alert_sent_once_per_cycle(monkeypatch):
    """open 告警同一熔断周期只发一次（去重防轰炸）。"""
    _reset_flags()
    monkeypatch.setattr(config, 'ALERT_SMTP_HOST', 'smtp.test.com')
    monkeypatch.setattr(config, 'ALERT_MAIL_TO', 'ops@test.com')
    sent = []

    def fake_send(subject, body):
        sent.append(subject)
        return True

    monkeypatch.setattr(alerter, '_send_mail', fake_send)
    assert alerter.send_breaker_alert('open', 3) is True
    assert alerter.send_breaker_alert('open', 3) is False, '同周期重复 open 不应再发'
    assert len(sent) == 1
    _reset_flags()


def test_reopen_independent_from_open(monkeypatch):
    """open 已发后，reopen（半开探测失败重熔）仍单独告警一次（升级事件）。"""
    _reset_flags()
    monkeypatch.setattr(config, 'ALERT_SMTP_HOST', 'smtp.test.com')
    monkeypatch.setattr(config, 'ALERT_MAIL_TO', 'ops@test.com')
    sent = []

    def fake_send(subject, body):
        sent.append(subject)
        return True

    monkeypatch.setattr(alerter, '_send_mail', fake_send)
    alerter.send_breaker_alert('open', 3)
    assert alerter.send_breaker_alert('reopen', 3) is True, 'reopen 是独立升级告警'
    assert alerter.send_breaker_alert('reopen', 3) is False, '同周期重复 reopen 不应再发'
    assert len(sent) == 2
    _reset_flags()


def test_reset_allows_next_cycle(monkeypatch):
    """恢复闭合（reset）后，下一熔断周期可再次告警。"""
    _reset_flags()
    monkeypatch.setattr(config, 'ALERT_SMTP_HOST', 'smtp.test.com')
    monkeypatch.setattr(config, 'ALERT_MAIL_TO', 'ops@test.com')
    sent = []

    def fake_send(subject, body):
        sent.append(subject)
        return True

    monkeypatch.setattr(alerter, '_send_mail', fake_send)
    alerter.send_breaker_alert('open', 3)
    alerter.reset_breaker_alert()
    assert alerter.send_breaker_alert('open', 3) is True, '重置后应可再次告警'
    assert len(sent) == 2
    _reset_flags()


def test_send_mail_failure_swallowed(monkeypatch):
    """SMTP 发送失败仅返回 False（记日志），不向上抛异常。"""
    _reset_flags()
    monkeypatch.setattr(config, 'ALERT_SMTP_HOST', 'smtp.test.com')
    monkeypatch.setattr(config, 'ALERT_MAIL_TO', 'ops@test.com')

    def boom(*a, **k):
        raise OSError('SMTP 连接失败')

    monkeypatch.setattr(alerter.smtplib, 'SMTP_SSL', boom)
    assert alerter._send_mail('主题', '正文') is False
    _reset_flags()


def test_send_mail_uses_ssl_for_465(monkeypatch):
    """端口 465 走 SMTP_SSL；发送成功后返回 True。"""
    _reset_flags()
    monkeypatch.setattr(config, 'ALERT_SMTP_HOST', 'smtp.test.com')
    monkeypatch.setattr(config, 'ALERT_SMTP_PORT', 465)
    monkeypatch.setattr(config, 'ALERT_MAIL_TO', 'ops@test.com')
    monkeypatch.setattr(config, 'ALERT_SMTP_USER', '')
    monkeypatch.setattr(config, 'ALERT_SMTP_PASS', '')

    class FakeServer:
        def __init__(self, *a, **k):
            pass

        def login(self, *a, **k):
            pass

        def sendmail(self, *a, **k):
            return {}

        def quit(self):
            pass

    monkeypatch.setattr(alerter.smtplib, 'SMTP_SSL', FakeServer)
    assert alerter._send_mail('主题', '正文') is True
    _reset_flags()
