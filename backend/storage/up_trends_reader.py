"""合并读层：从 SQLite 构造 UP 主动态分析结果

数据来源：
  - UP 维度（play_ranking / creator_ranking / summary / up_details）→ up_obs 表
  - 视频维度（timeline / hot_videos / content_types / keyword_cloud）→ video_obs_snapshot 表

返回结构：与 analysis 契约一致，多两个调试字段：
  _read_from: 'up_obs+video_obs'
  _up_obs_ts: int（便于定位批次）
"""
import os
from storage.up_obs_reader import (
    get_latest_batch_ts, get_play_ranking, get_creator_ranking, get_summary,
    get_up_details,
)
from storage.video_snapshot_reader import get_video_snapshot_fields, get_timeline_history

# 环境变量保留兼容性（默认 'db'，仅 'db' 有效）
READ_FROM = os.getenv('UP_TRENDS_READ_FROM', 'db')


def _apply_pool_summary(summary, pool):
    """用视频池求和覆盖 summary 的总量字段（pool 缺失时原样返回）。

    背景：summary 的 total_views 若走 up_obs 的 SUM(views_30d) 是"owner 归属后按 UP 求和"，
    owner 不在追踪名单的视频会缺失；pool_summary 是分析任务内"近7天去重视频播放量直接相加"
    （联合投稿只计一次），才是总播放量的唯一真源。两者口径需在 summary 层面统一。

    同时写入显式 pool_* 字段，供前端明确读取视频池口径（老批次无 pool_summary 则不存在这些键）。
    """
    if not pool:
        return summary
    s = dict(summary)
    s['total_views'] = pool.get('total_views', s.get('total_views', 0))
    s['total_videos'] = pool.get('total_videos', s.get('total_videos', 0))
    s['avg_views_per_video'] = pool.get('avg_views_per_video', s.get('avg_views_per_video', 0))
    s['pool_total_views'] = pool.get('total_views', 0)
    s['pool_total_videos'] = pool.get('total_videos', 0)
    s['pool_avg_views_per_video'] = pool.get('avg_views_per_video', 0)
    return s


def load_analysis():
    """返回最新分析结果（从数据库构造，前端零感知）。

    UP 维度走 up_obs，视频维度走 video_obs_snapshot，完全从数据库构造。

    返回: dict（含 created_at / tracked_up_count / analysis / up_details）或 None
    """
    ts = get_latest_batch_ts()
    if not ts:
        return None  # up_obs 无数据（首次部署或表被清空）

    # UP 维度
    play_ranking = get_play_ranking(ts)
    creator_ranking = get_creator_ranking(ts)
    summary = get_summary(ts)
    up_details = get_up_details(ts)

    # 视频维度
    video_fields = get_video_snapshot_fields(ts)

    # 总播放量/视频数/平均播放改用视频池求和（pool_summary），见 _apply_pool_summary 注释
    summary = _apply_pool_summary(summary, video_fields.get('pool_summary'))

    analysis = {
        'play_ranking': play_ranking,
        'creator_ranking': creator_ranking,
        'summary': summary,
        'timeline': video_fields.get('timeline', []),
        'hot_videos': video_fields.get('hot_videos', []),
        'content_types': video_fields.get('content_types', []),
        'keyword_cloud': video_fields.get('keyword_cloud', []),
        '_read_from': 'up_obs+video_obs',
        '_up_obs_ts': ts,
    }

    return {
        'created_at': ts,
        'tracked_up_count': len(up_details),
        'analysis': analysis,
        'up_details': up_details,
    }


def load_history_batches(start_ts, end_ts):
    """返回历史批次列表（用于趋势图），每批含完整 analysis

    从 video_obs_snapshot 拿 ts + timeline，从 up_obs 拿 summary + play_ranking，
    合并成前端 TrendCharts 可直接消费的 batches 结构。

    返回: list[dict]，每个元素形如：
      {
        'created_at': ts,
        'analysis': {
            'timeline': [...],
            'summary': {...},
            'play_ranking': [...],
        }
      }
    """
    batches = get_timeline_history(start_ts, end_ts)
    for b in batches:
        ts = b['created_at']
        summary = get_summary(ts)
        # 历史批次也统一用视频池口径（老批次无 pool_summary 时保持 up_obs 聚合）
        pool = get_video_snapshot_fields(ts, ['pool_summary']).get('pool_summary')
        b['analysis']['summary'] = _apply_pool_summary(summary, pool)
        b['analysis']['play_ranking'] = get_play_ranking(ts)
    return batches
