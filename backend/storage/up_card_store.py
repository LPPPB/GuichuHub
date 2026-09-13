"""up_card_cache 缓存表读写（UP 卡片数据：词云/分区标签/统计）。

职责：get_up_card 的持久化缓存，TTL 1 天。
- read_up_card_cache(mid)：未命中 / 过期返回 None
- write_up_card_cache(mid, card)：INSERT OR REPLACE 幂等写入
表结构见 db.py _SCHEMA_V9。
"""

import json
import time
from storage.db import get_conn

CACHE_TTL = 86400  # 1 天


def read_up_card_cache(mid):
    """读取未过期的 UP 卡片缓存，无/过期/损坏返回 None"""
    conn = get_conn()
    row = conn.execute(
        'SELECT payload_json, fetched_at FROM up_card_cache WHERE mid=?', (mid,)
    ).fetchone()
    if not row:
        return None
    payload, fetched_at = row
    if time.time() - fetched_at > CACHE_TTL:
        return None
    try:
        data = json.loads(payload)
    except (ValueError, TypeError):
        return None
    # 口径升级：旧缓存无 last_7d_views 字段（30天口径 / last_month_* 字段名）→ 视为过期重新抓取
    # （一次性失效：字段名带 7d 标记，随 TTL 自然覆盖后无需再失效）
    if not isinstance(data, dict) or 'last_7d_views' not in data:
        return None
    return data


def write_up_card_cache(mid, card):
    """幂等写入 UP 卡片缓存"""
    conn = get_conn()
    conn.execute(
        'INSERT OR REPLACE INTO up_card_cache (mid, payload_json, fetched_at) VALUES (?, ?, ?)',
        (mid, json.dumps(card, ensure_ascii=False), int(time.time())),
    )
    conn.commit()
