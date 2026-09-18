"""PostgreSQL JSONB snapshot reader for video-dimensional analysis.

  - 只读不写，与 db.py 的写入职责分离
  - JSONB payload 直接返回，前端零感知
  - 字段名与 analysis 字段对齐

读取场景：
  1. 最新批次 4 字段：timeline / hot_videos / content_types / keyword_cloud
  2. 历史 timeline：/api/up-trends/history 的数据源
"""
from collections import defaultdict
from storage.db import get_business_repository


# 合法字段白名单（与 db.py._VIDEO_SNAPSHOT_FIELDS 对齐）
_FIELDS = ('timeline', 'hot_videos', 'all_videos', 'content_types', 'keyword_cloud', 'pool_summary')


def _repository():
    repository = get_business_repository()
    if repository is None:
        raise RuntimeError('PostgreSQL business repository is not configured')
    return repository


def get_video_snapshot_fields(ts, fields=None):
    """从 video_obs_snapshot 读取指定字段

    参数:
      ts: 批次时刻
      fields: ['timeline', 'hot_videos', ...] 或 None（返回全部 4 个）

    返回: dict，key=field, value=反序列化后的 list[dict]
          未找到的 field 不会出现在返回 dict 里（调用方用 .get(field, []) 兜底）
    """
    wanted = tuple(fields) if fields else _FIELDS
    # 校验白名单（防 SQL 注入，虽然用占位符但保持防御性）
    for f in wanted:
        if f not in _FIELDS:
            raise ValueError(f'非法 field: {f}，允许: {sorted(_FIELDS)}')

    return _repository().snapshot_fields(ts, wanted)


def get_timeline_history(start_ts, end_ts):
    """读历史 timeline（/api/up-trends/history 的数据源）

    返回结构前端 TrendCharts 可直接消费：
      [{
        'created_at': ts,           # 批次时刻（前端用作批次标签）
        'analysis': {
            'timeline': [...]       # 该批次的 timeline 数组
        }
      }, ...]

    参数:
      start_ts: 起始时刻（含）
      end_ts: 结束时刻（含）
    """
    rows = _repository().snapshot_documents_between(('timeline',), start_ts, end_ts)
    return [{
        'created_at': row['ts'],
        'analysis': {'timeline': row['payload']},
    } for row in rows]


def get_batch_ts_list(start_ts, end_ts):
    """返回时间范围内的所有批次 ts 列表（升序）

    用于 /history 端点的 tracked_count 聚合或调试。
    """
    return sorted({row['ts'] for row in _repository().snapshot_documents_between(
        _FIELDS, start_ts, end_ts,
    )})


def get_hot_growth_videos(lookback_days=14, limit=10):
    """高增速视频榜：追踪 UP 主视频中播放量增速最快的。

    数据源：video_obs_snapshot 的 all_videos（新批次全量视频）/ hot_videos（老批次
    播放量 TOP10 兜底——历史批次只有该字段，两者同批次 views 一致）。

    增速口径：取每个 bvid 的最新观测 vs 距其 >= MIN_GAP_HOURS 的最近观测点，
      speed = (最新播放 - 起点播放) / 间隔小时   ← 每小时播放增量，排序主键
    附带增量 / 倍率 / 观测点迷你趋势线，供前端多维度展示。
    仅统计观测点 >= 2 且最近间隔播放净增长的视频（停涨/倒退不入榜）。

    MIN_GAP_HOURS=1：分析批次间隔极不均匀（用户连点刷新可短至几分钟），
    间隔过短时增量噪声除以极小时间会被极端放大（如 0.1h 内 +62 播放 → 620/时），
    起点必须距最新观测至少 1 小时，过滤分钟级噪声，保证增速口径稳定。
    """
    MIN_GAP_HOURS = 1.0
    repository = _repository()
    latest_ts = repository.latest_snapshot_ts(('all_videos', 'hot_videos'))
    if not latest_ts:
        return []

    since = latest_ts - lookback_days * 86400
    rows = repository.snapshot_documents_between(
        ('all_videos', 'hot_videos'), since, latest_ts,
    )

    obs = defaultdict(list)  # bvid -> [{ts, views}, ...]（同批次双字段去重）
    meta = {}
    seen_keys = set()
    for r in rows:
        videos = r['payload']
        if not isinstance(videos, list):
            continue  # 非列表 payload（手工编辑/旧版本写入的 dict 等）视为异常跳过
        for v in videos:
            bvid = v.get('bvid')
            if not bvid:
                continue  # 缺 bvid 的脏数据跳过
            try:
                # B 站部分字段可能以字符串数字返回，int() 归一；非数字视为异常数据跳过
                views = int(v.get('views'))
            except (TypeError, ValueError):
                continue
            key = (bvid, r['ts'])
            if key in seen_keys:
                continue  # 同一批次 all_videos 与 hot_videos 都可能含该视频，去重
            seen_keys.add(key)
            obs[bvid].append({'ts': r['ts'], 'views': views})
            if bvid not in meta:
                meta[bvid] = {
                    'bvid': bvid,
                    'title': v.get('title', '') or '',
                    'cover': v.get('cover', '') or '',
                    'url': v.get('url', '') or f'https://www.bilibili.com/video/{bvid}',
                    'pub_date': v.get('pub_date', 0) or 0,
                    # 与前端热门TOP10 的 authors 解析契约一致（_coauthors 优先，否则单作者构造）
                    '_coauthors': v.get('_coauthors') or (
                        [{'mid': v.get('up_mid'), 'name': v.get('up_name')}] if v.get('up_name') else []
                    ),
                }

    results = []
    for bvid, pts in obs.items():
        if len(pts) < 2:
            continue  # 仅出现一次的观测点无法算增速
        pts.sort(key=lambda p: p['ts'])
        latest = pts[-1]
        # 起点：距最新观测 >= MIN_GAP_HOURS 的最近观测点（过滤分钟级批次噪声）
        prev = next(
            (p for p in reversed(pts[:-1]) if latest['ts'] - p['ts'] >= MIN_GAP_HOURS * 3600),
            None,
        )
        if not prev:
            continue  # 全部历史观测都在最短间隔内，样本太短无法可靠算增速
        delta = latest['views'] - prev['views']
        if delta <= 0:
            continue  # 停涨或数据异常，不入增速榜
        hours = (latest['ts'] - prev['ts']) / 3600.0
        if hours <= 0:
            continue
        growth_rate = (delta / prev['views'] * 100) if prev['views'] else None
        results.append({
            **meta[bvid],
            'views': latest['views'],
            'prev_views': prev['views'],
            'growth_views': delta,
            'growth_rate': round(growth_rate, 1) if growth_rate is not None else None,
            'speed': round(delta / hours, 1),
            'hours': round(hours, 1),
            'obs_count': len(pts),
            'latest_ts': latest['ts'],
            'spark': [p['views'] for p in pts],
        })

    results.sort(key=lambda x: x['speed'], reverse=True)
    return results[:limit]
