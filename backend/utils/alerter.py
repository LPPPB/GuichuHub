# -*- coding: utf-8 -*-
"""告警通知 — 邮件告警（SMTP），供同接熔断器等异常事件调用。

设计：
- 配置来自 config.py（.env）：ALERT_SMTP_HOST / PORT / USER / PASS / MAIL_TO，
  未配置 SMTP（host 或收件人为空）时静默跳过，仅日志、绝不阻断主流程。
- 按事件类型去重：同一熔断周期（打开→闭合之间）最多各发一次 open/reopen 告警，
  恢复闭合时重置标志，避免风控持续期间的邮件轰炸。
- 发送失败仅记录 warning，不影响调用方。

用法：
    from utils.alerter import send_breaker_alert, reset_breaker_alert
    send_breaker_alert('open', fails=3)    # 熔断打开 / 半开探测失败重熔
    reset_breaker_alert()                  # 恢复闭合时重置去重标志
"""
import smtplib
import time
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr

import config
from logger import get_logger

_log = get_logger(__name__)

# 当前熔断周期的告警去重标志（恢复闭合时由 reset_breaker_alert 重置）
_sent_flags = {'open': False, 'reopen': False}


def _smtp_configured():
    """SMTP 是否已配置（动态读 config，便于测试 monkeypatch）。"""
    return bool(config.ALERT_SMTP_HOST and config.ALERT_MAIL_TO)


def _send_mail(subject, body):
    """发送一封纯文本邮件。未配置/发送失败均静默处理，返回是否成功。"""
    if not _smtp_configured():
        _log.info(f'[告警邮件] 未配置 SMTP，跳过发送: {subject}')
        return False
    # 支持逗号分隔多收件人（ALERT_MAIL_TO="a@x.com,b@y.com"）
    to_list = [a.strip() for a in config.ALERT_MAIL_TO.split(',') if a.strip()]
    if not to_list:
        _log.info(f'[告警邮件] 收件人列表为空，跳过发送: {subject}')
        return False
    msg = MIMEText(body, 'plain', 'utf-8')
    msg['Subject'] = Header(subject, 'utf-8')
    msg['From'] = formataddr(('鬼畜热度看板', config.ALERT_SMTP_USER or config.ALERT_SMTP_HOST))
    msg['To'] = ', '.join(to_list)
    try:
        if config.ALERT_SMTP_PORT == 465:
            server = smtplib.SMTP_SSL(config.ALERT_SMTP_HOST, config.ALERT_SMTP_PORT, timeout=10)
        else:
            server = smtplib.SMTP(config.ALERT_SMTP_HOST, config.ALERT_SMTP_PORT, timeout=10)
            try:
                # 587/25 通常走 STARTTLS；但部分内网/测试服务器不支持，
                # 失败降级明文发送（记 warning 不阻断），避免告警因 TLS 不可用全丢
                server.starttls()
            except smtplib.SMTPException:
                _log.warning('[告警邮件] STARTTLS 不可用，降级明文发送')
        if config.ALERT_SMTP_USER:
            server.login(config.ALERT_SMTP_USER, config.ALERT_SMTP_PASS)
        server.sendmail(config.ALERT_SMTP_USER or config.ALERT_SMTP_HOST,
                        to_list, msg.as_string())
        server.quit()
        _log.info(f'[告警邮件] 已发送: {subject}')
        return True
    except Exception as e:
        # 发送失败只记日志，绝不向上抛出影响主流程
        _log.warning(f'[告警邮件] 发送失败: {e}')
        return False


def send_breaker_alert(state, fails):
    """熔断事件邮件告警（open=首次熔断 / reopen=半开探测失败重熔）。

    同一熔断周期内每类事件只发一次（去重防轰炸）；恢复闭合后由
    reset_breaker_alert 重置，下次熔断可再次告警。
    """
    if state not in _sent_flags:
        return False
    if _sent_flags[state]:
        return False  # 本周期已发过该类告警
    labels = {
        'open': ('同接抓取熔断告警', '同接请求连续失败触发熔断保护，已停止发起同接请求（防风控升级）。'),
        'reopen': ('同接熔断恢复失败告警', '冷却到期后半开探测失败，熔断重新打开（风控可能未解除）。'),
    }
    title, desc = labels[state]
    subject = f'【鬼畜热度看板】{title}'
    body = (
        f'{desc}\n\n'
        f'事件: {state}\n'
        f'时间: {time.strftime("%Y-%m-%d %H:%M:%S")}\n'
        f'失败计数: {fails}（阈值 {config.ONLINE_BREAK_THRESHOLD}）\n'
        f'冷却时长: {config.ONLINE_BREAK_COOLDOWN}s\n'
        f'半开探测配额: {config.ONLINE_BREAK_HALF_OPEN_LIMIT}\n\n'
        f'系统将在冷却到期后自动半开探测恢复；请检查 B 站 Cookie/登录态是否失效。'
    )
    ok = _send_mail(subject, body)
    if ok:
        _sent_flags[state] = True
    return ok


def reset_breaker_alert():
    """熔断恢复闭合时重置告警去重标志（下次熔断可再次告警）。"""
    _sent_flags.update({'open': False, 'reopen': False})


def get_alert_flags():
    """当前告警去重标志快照（测试/排查用）。"""
    return dict(_sent_flags)
