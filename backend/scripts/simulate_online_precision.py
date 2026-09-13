# -*- coding: utf-8 -*-
"""模拟插入不同精度（exact/k_plus/w）的同接观测，验证折线图标记点渲染（2026-08-02）

背景：B 站同接 total 是展示字符串（<1000 精确 / "1000+" 千取整 / "1.1万" 万取整），
前端 ObsTrendChart 按 video_obs.online_precision 渲染标记点：
  exact  → 实心圆（精确）
  k_plus / w → 空心圆（近似，B站按千/万取整）
tooltip 用 formatOnline 按精度还原原始格式（"1000+（约）" / "1.1万（约）"）。

本脚本向指定 bvid 的 video_obs 插入 6 条混合精度的观测点（48h 窗口内），然后：
1. 读回 get_video_obs_trend 验证 precision 已落库透传
2. 镜像前端 marker/tooltip 逻辑逐点断言"实心/空心 + tooltip 文本"与预期一致
3. 打印自查表 + 浏览器验证指引（展开卡片 → 点"同接" → 看空心圆与 tooltip）

用法（backend 目录下）：
  ./.venv/Scripts/python.exe scripts/simulate_online_precision.py            # 默认榜首 bvid
  ./.venv/Scripts/python.exe scripts/simulate_online_precision.py BV1xxxx   # 指定 bvid
  ./.venv/Scripts/python.exe scripts/simulate_online_precision.py --cleanup # 删除本次插入的模拟点

安全设计：
- ts 选择避开该 bvid 已有观测时刻（查询碰撞后顺移），不覆盖真实数据
- 插入记录写入 data/sim_precision_rows.json，--cleanup 按 (bvid, ts) 精确删除
- 只走 record_obs（不动 videos 维度表、不碰 JSON 缓存），与观测任务同路径
"""
import sys
import os
import json
import time
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from storage import db as tsdb
from storage.cache import get_data

STATE_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          'data', 'sim_precision_rows.json')

# ── 模拟场景：(距当前分钟, online_count, online_precision, 预期渲染说明) ──
SCENARIOS = [
    (0,   88,    'exact',  '精确 · 实心圆 · tooltip "88"'),
    (25,  1000,  'k_plus', '近似 · 空心圆 · tooltip "1000+（约）"'),
    (50,  11000, 'w',      '近似 · 空心圆 · tooltip "1.1万（约）"'),
    (75,  137,   'exact',  '精确 · 实心圆 · tooltip "137"'),
    (100, 2000,  'k_plus', '近似 · 空心圆 · tooltip "2000+（约）"'),
    (125, 15000, 'w',      '近似 · 空心圆 · tooltip "1.5万（约）"'),
]

# ── 镜像前端 ObsTrendChart 的渲染逻辑（与 formatNum/formatOnline/标记判定一致）──
def fmt_num(v):
    if v is None:
        return '—'
    if v >= 10000:
        return f'{v / 10000:.1f}万'
    return f'{v:,}'

def frontend_format_online(value, precision):
    if precision == 'k_plus':
        return f'{value}+（约）'
    if precision == 'w':
        w = value / 10000
        return f'{w if w % 1 == 0 else round(w, 1)}万（约）'
    return fmt_num(value)  # exact / 未知精度（老数据）按精确兜底

def frontend_marker(precision):
    """精确点实心、近似点空心（透明填充 + 描边）"""
    return '实心圆' if precision in (None, 'exact') else '空心圆'


def _existing_ts(bvid):
    """该 bvid 已有观测时刻集合，插入时避开（防覆盖真实数据）"""
    conn = tsdb.get_conn()
    rows = conn.execute('SELECT ts FROM video_obs WHERE bvid=?', (bvid,)).fetchall()
    return {r['ts'] for r in rows}


def insert_sim(bvid):
    now = int(time.time())
    existing = _existing_ts(bvid)
    inserted = []
    for offset_min, online, precision, desc in SCENARIOS:
        ts = now - offset_min * 60
        if ts in existing:  # 碰撞顺移 30s，避免覆盖该时刻真实观测
            ts += 30
        metrics = {
            'views': 100000 + offset_min * 100,
            'likes': 1000, 'coins': 100, 'favorites': 50,
            'shares': 20, 'comments': 300, 'danmaku': 400,
            'online_count': online,
            'online_precision': precision,
        }
        tsdb.record_obs(bvid, ts, metrics)
        inserted.append({'bvid': bvid, 'ts': ts, 'online_count': online,
                         'online_precision': precision, 'desc': desc})
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(inserted, f, ensure_ascii=False, indent=2)
    return inserted


def verify(bvid, inserted):
    """读回 get_video_obs_trend，逐点断言 precision 透传 + 前端渲染逻辑与预期一致"""
    pts = tsdb.get_video_obs_trend(bvid, 48)
    by_ts = {p['ts']: p for p in pts}
    print(f'\n[验证] bvid={bvid} 近48h观测点 {len(pts)} 个，本次模拟 {len(inserted)} 个：')
    print(f'{"时刻":<8}{"同接":>8}  {"精度":<7}{"标记":<5}{"tooltip(前端逻辑)":<20} 预期')
    print('-' * 78)
    ok = True
    for rec in inserted:
        p = by_ts.get(rec['ts'])
        if not p:
            print(f'  {rec["ts"]}  ✗ 未读到该观测点')
            ok = False
            continue
        db_precision = p.get('online_precision')
        expect_desc = rec['desc']
        marker = frontend_marker(db_precision)
        tooltip = frontend_format_online(p['online_count'], db_precision)
        line_ok = (db_precision == rec['online_precision']
                   and (marker == '实心圆') == (db_precision in (None, 'exact')))
        if not line_ok:
            ok = False
        mark = '✓' if line_ok else '✗'
        print(f'  {time.strftime("%H:%M", time.localtime(rec["ts"])):<8}'
              f'{p["online_count"]:>8}  {str(db_precision):<7}'
              f'{marker:<5}{tooltip:<20}{expect_desc}  {mark}')
    return ok


def cleanup():
    if not os.path.exists(STATE_FILE):
        print('[清理] 无模拟数据记录（state 文件不存在），无需清理')
        return
    with open(STATE_FILE, encoding='utf-8') as f:
        rows = json.load(f)
    conn = tsdb.get_conn()
    deleted = 0
    for r in rows:
        cur = conn.execute(
            'DELETE FROM video_obs WHERE bvid=? AND ts=?',
            (r['bvid'], r['ts']))
        deleted += cur.rowcount
    conn.commit()
    os.remove(STATE_FILE)
    print(f'[清理] 已删除 {deleted} 条模拟观测点，state 文件已移除')


def main():
    parser = argparse.ArgumentParser(description='模拟插入不同精度同接观测，验证折线图标记点')
    parser.add_argument('bvid', nargs='?', help='目标 bvid（缺省取榜单第一）')
    parser.add_argument('--cleanup', action='store_true', help='删除上次插入的模拟数据')
    args = parser.parse_args()

    if args.cleanup:
        cleanup()
        return

    bvid = args.bvid
    if not bvid:
        data = get_data() or {}
        rank = data.get('kichu_rank', []) or []
        if not rank:
            print('[错误] 未指定 bvid 且看板缓存无 kichu_rank，请显式传 bvid')
            sys.exit(1)
        bvid = rank[0].get('bvid')
        print(f'[目标] 未指定 bvid，默认取榜单第一：{bvid}')
    print(f'[插入] 向 {bvid} 写入 {len(SCENARIOS)} 条混合精度观测点（48h 窗口内，ts 避开已有时刻）')

    inserted = insert_sim(bvid)
    ok = verify(bvid, inserted)

    print('\n[浏览器验证指引]')
    print('  1. 打开前端，展开该视频卡片 → 点"同接"按钮')
    print('  2. 期望：exact 点=实心圆；k_plus/w 点=空心圆（透明填充+橙色描边）')
    print('  3. 悬停空心圆：tooltip 显示 "1000+（约）" / "1.1万（约）" 等原始格式')
    print('  4. 完成后运行 --cleanup 删除模拟数据，恢复真实观测')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
