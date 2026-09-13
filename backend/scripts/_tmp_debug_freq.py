# -*- coding: utf-8 -*-
"""临时排查：UP 分析/全量抓取的耗时与风控证据。跑完即删。"""
import sqlite3, os, datetime

db = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'kichu_board.db')
conn = sqlite3.connect(db)
conn.row_factory = sqlite3.Row

def ts2str(ts):
    return datetime.datetime.fromtimestamp(ts).strftime('%m-%d %H:%M') if ts else '?'

# 1. crawl_runs 表结构
print('=== crawl_runs 列 ===')
cols = [r['name'] for r in conn.execute('PRAGMA table_info(crawl_runs)').fetchall()]
print(cols)

# 2. crawl_runs 最近 20 次成功抓取的耗时
print('\n=== crawl_runs 最近 20 次（按时间倒序）===')
rows = conn.execute('SELECT * FROM crawl_runs ORDER BY rowid DESC LIMIT 20').fetchall()
for r in rows:
    d = dict(r)
    # 找耗时字段（start_time/end_time 或 created_at/finished_at）
    print({k: d[k] for k in d})

# 3. 统计成功/失败
print('\n=== crawl_runs status 统计 ===')
for r in conn.execute('SELECT status, COUNT(*) as c FROM crawl_runs GROUP BY status').fetchall():
    print(dict(r))

# 4. up_obs 批次 ts 分布（UP 分析频率）
print('\n=== up_obs 最近 15 批 ts（UP 分析实际跑的时间点）===')
for r in conn.execute('SELECT ts, COUNT(*) as up_count FROM up_obs GROUP BY ts ORDER BY ts DESC LIMIT 15').fetchall():
    print(f'  {ts2str(r["ts"])} (ts={r["ts"]}) — {r["up_count"]} 个 UP')

# 5. video_obs_snapshot 批次 ts
print('\n=== video_obs_snapshot 最近 15 批 ts ===')
for r in conn.execute('SELECT ts, COUNT(*) as fields FROM video_obs_snapshot GROUP BY ts ORDER BY ts DESC LIMIT 15').fetchall():
    print(f'  {ts2str(r["ts"])} (ts={r["ts"]}) — {r["fields"]} 个 field')

# 6. video_obs 最近观测批次（crawl_jobs 每 30 分钟）
print('\n=== video_obs 最近 10 批 ts（crawl_jobs 观测频率）===')
for r in conn.execute('SELECT ts, COUNT(*) as cnt FROM video_obs GROUP BY ts ORDER BY ts DESC LIMIT 10').fetchall():
    print(f'  {ts2str(r["ts"])} — {r["cnt"]} 条观测')
