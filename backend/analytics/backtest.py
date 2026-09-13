# -*- coding: utf-8 -*-
"""回测模块：验证潜力分公式的预测力（V1：记录分事后验证）。

核心思想：潜力分是"批内归一"的排序模型。回测 = 用历史观测数据验证一句话——
"当时排在前面的视频，之后是否真的更火？"

数据基础（video_obs 每轮观测存了原始指标 + potential_score=当时评分）：
  1. 选一个历史批次 T（该批次有 potential_score 的行 = 当时的评分榜单）
  2. 取每个视频在 [T, T+window] 内最后一次观测的播放量 → 窗口播放增量/增速
  3. 评估当时评分对未来表现的预测力：
     - Spearman：当时分 vs 后来增速（排序一致性）
     - Top-N 命中率：后来增量 Top N 中有多少来自当时分 Top N
     - 分桶单调性：按当时分等频分桶，各组后来平均增速是否递增

V1 不做公式重放：直接用已记录的 potential_score（当时真实计算值），
避免重建候选池/同接平滑/trend 的历史快照，先验证"评分是否具备预测力"。
公式重放（带/不带 trend 等版本对比）留待 V2。
"""
import math
import time

from storage import db


def _rank(values):
    """平均秩（处理并列）：[10,20,20,30] -> [1.0, 2.5, 2.5, 4.0]"""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i, n = 0, len(values)
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0  # 平均秩（1 基）
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(x, y):
    """Spearman 秩相关系数（无 scipy 依赖）。n<2 或任一方差为零时返回 0.0"""
    n = len(x)
    if n < 2:
        return 0.0
    rx, ry = _rank(x), _rank(y)
    mx = sum(rx) / n
    my = sum(ry) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = sum((a - mx) ** 2 for a in rx)
    dy = sum((b - my) ** 2 for b in ry)
    if dx == 0 or dy == 0:
        return 0.0
    return cov / ((dx * dy) ** 0.5)


def list_scored_batches():
    """有 potential_score 的历史批次（时间倒序），供回测面板选择 T"""
    conn = db.get_conn()
    rows = conn.execute('''
        SELECT ts, COUNT(*) AS cnt
        FROM video_obs
        WHERE potential_score IS NOT NULL AND views IS NOT NULL
        GROUP BY ts
        ORDER BY ts DESC
    ''').fetchall()
    return [{
        'ts': r['ts'],
        'count': r['cnt'],
        'time': time.strftime('%m-%d %H:%M', time.localtime(r['ts'])),
    } for r in rows]


def run_backtest(ts, window_hours=48, top_n=20, min_views=100):
    """在历史批次 T 重放评分榜单，评估对未来 window 内播放表现（增量/增速）的预测力。

    min_views：播放量低于该值的视频跳过（太冷，增速分母不稳无意义）。
    """
    conn = db.get_conn()
    end_ts = ts + window_hours * 3600
    rows = conn.execute('''
        SELECT bvid, views, potential_score FROM video_obs
        WHERE ts=? AND potential_score IS NOT NULL AND views IS NOT NULL
    ''', (ts,)).fetchall()

    items = []
    unverified = 0
    for r in rows:
        views_t = r['views']
        if views_t < min_views:
            continue
        later = conn.execute('''
            SELECT views FROM video_obs
            WHERE bvid=? AND ts>? AND ts<=? AND views IS NOT NULL
            ORDER BY ts DESC LIMIT 1
        ''', (r['bvid'], ts, end_ts)).fetchone()
        if not later:
            unverified += 1
            continue
        views_later = later['views']
        delta = views_later - views_t
        items.append({
            'bvid': r['bvid'],
            'views_at_T': views_t,
            'views_later': views_later,
            'views_delta': delta,
            # 不 round：增长率 <0.00005 会被 4 位小数截成 0.0，导致 Spearman 排名
            # 与增速排序出现并列失真；展示层（前端 *100 格式化 / avg_growth）再取整
            'growth_rate': delta / views_t,
            'score': r['potential_score'],
        })

    # 当时榜单排名（按分降序）与后来表现排名（按增量降序）
    items.sort(key=lambda it: it['score'], reverse=True)
    for i, it in enumerate(items):
        it['rank_at_T'] = i + 1
    later_sorted = sorted(items, key=lambda it: it['views_delta'], reverse=True)
    for i, it in enumerate(later_sorted):
        it['later_rank'] = i + 1

    n = len(items)
    top_n = min(top_n, max(n, 1))
    top_by_score = set(it['bvid'] for it in items[:top_n])
    top_by_delta = set(it['bvid'] for it in later_sorted[:top_n])
    growth_sorted = sorted(items, key=lambda it: it['growth_rate'], reverse=True)
    top_by_growth = set(it['bvid'] for it in growth_sorted[:top_n])

    # 当时 Top N 在后来榜单中的升降（相对当时排名）
    up = down = same = 0
    for it in items[:top_n]:
        if it['later_rank'] < it['rank_at_T']:
            up += 1
        elif it['later_rank'] > it['rank_at_T']:
            down += 1
        else:
            same += 1

    # 等频分桶（按当时分），看各组后来平均增速是否单调递增
    buckets = []
    if n:
        scores_sorted = sorted(items, key=lambda it: it['score'])
        size = math.ceil(n / 5)
        for bi in range(5):
            part = scores_sorted[bi * size:(bi + 1) * size]
            if not part:
                continue
            lo = min(x['score'] for x in part)
            hi = max(x['score'] for x in part)
            buckets.append({
                'name': f'组{bi + 1} · {lo:.1f}~{hi:.1f}分',
                'n': len(part),
                'avg_delta': round(sum(x['views_delta'] for x in part) / len(part)),
                'avg_growth': round(sum(x['growth_rate'] for x in part) / len(part), 4),
            })

    # 标题/作者（分块 IN 查询，避免 SQLite 变量数上限 999）
    info = {}
    bvids = [it['bvid'] for it in items]
    for i in range(0, len(bvids), 500):
        chunk = bvids[i:i + 500]
        ph = ','.join('?' * len(chunk))
        for r in conn.execute(f'''
            SELECT v.bvid, v.title, u.name AS author FROM videos v
            LEFT JOIN ups u ON u.mid = v.mid
            WHERE v.bvid IN ({ph})
        ''', chunk):
            info[r['bvid']] = dict(r)

    return {
        'meta': {
            'ts': ts,
            'time': time.strftime('%m-%d %H:%M', time.localtime(ts)),
            'window_hours': window_hours,
            'top_n': top_n,
            'n_scored': len(rows),          # 当时有分的视频数
            'n_verified': n,                # 窗口内有后续观测、可验证数
            'n_unverified': unverified,     # 窗口内无后续观测（冷门停测等）
        },
        'metrics': {
            'spearman': round(spearman([it['score'] for it in items],
                                       [it['growth_rate'] for it in items]), 3),
            'hit_rate_delta': round(len(top_by_score & top_by_delta) / top_n, 3),
            'hit_rate_growth': round(len(top_by_score & top_by_growth) / top_n, 3),
            'rank_up': up,
            'rank_down': down,
            'rank_same': same,
        },
        'buckets': buckets,
        'scatter': [{
            'bvid': it['bvid'],
            'score': it['score'],
            'growth_rate': it['growth_rate'],
            'views_delta': it['views_delta'],
        } for it in items],
        'table': [{
            'bvid': it['bvid'],
            'title': (info.get(it['bvid']) or {}).get('title') or '',
            'author': (info.get(it['bvid']) or {}).get('author') or '',
            'score': it['score'],
            'rank_at_T': it['rank_at_T'],
            'views_at_T': it['views_at_T'],
            'views_delta': it['views_delta'],
            'growth_rate': it['growth_rate'],
            'later_rank': it['later_rank'],
        } for it in sorted(items, key=lambda x: x['rank_at_T'])],
    }


def get_dev_stats():
    """数据体检：DB 健康概览（schema 版本、批次、抓取残留、行数）"""
    conn = db.get_conn()
    runs = {r['status']: r['c'] for r in conn.execute(
        'SELECT status, COUNT(*) c FROM crawl_runs GROUP BY status')}
    stale = conn.execute('''
        SELECT id, started_at, trigger_source FROM crawl_runs
        WHERE status='running' ORDER BY started_at DESC LIMIT 20
    ''').fetchall()
    vo = conn.execute('SELECT COUNT(DISTINCT ts) b, COUNT(*) r FROM video_obs').fetchone()
    schema = conn.execute('SELECT MAX(version) v FROM schema_version').fetchone()['v']
    return {
        'schema_version': schema,
        'crawl_runs': runs,
        'stale_running': [{
            'id': r['id'],
            'started_at': time.strftime('%m-%d %H:%M', time.localtime(r['started_at'])),
            'trigger': r['trigger_source'],
        } for r in stale],
        'video_obs_batches': vo['b'],
        'video_obs_rows': vo['r'],
        'videos': conn.execute('SELECT COUNT(*) c FROM videos').fetchone()['c'],
        'ups': conn.execute('SELECT COUNT(*) c FROM ups').fetchone()['c'],
    }
