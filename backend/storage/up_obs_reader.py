"""PostgreSQL UP-observation reader (read-only; writes remain in repositories).

返回 analysis 契约所需的 play_ranking/creator_ranking/summary/up_details，前端零感知。
JOIN ups 表拿 name/face。

字段映射（易错点）：
  play_ranking.video_count         ← up_obs.video_count_total（V3 补列）
  play_ranking.total_recent_views  ← up_obs.views_30d
  creator_ranking.recent_video_count ← up_obs.video_count_30d
  *.kichu_video_count              ← up_obs.kichu_count
  *.latest_pub_date                ← up_obs.latest_pub_ts

注：views_30d / video_count_30d 列名保留（30d），但语义 2026-08-03 起为"近7天"
（VIEW_RECENT_DAYS=7，见 bilibili_user.py）；历史批次已清空重跑，不再有 30 天口径数据。

summary 聚合：
  total_ups            ← COUNT(*) FROM up_obs WHERE ts=?
  total_views          ← SUM(views_30d)
  kichu_up_count       ← SUM(CASE WHEN kichu_count>0 THEN 1 ELSE 0 END)
  active_up_count      ← SUM(CASE WHEN latest_pub_ts > now-7d THEN 1 ELSE 0 END)
  up_details (全量)    ← up_obs JOIN ups（无 LIMIT）

已知近似缺口（语义不同，不算错误）：
  summary.total_videos / kichu_video_count / avg_views_per_video：
    属于视频维度聚合，up_obs 无视频级数据，用 video_count_30d 近似
  up_details.sign / following_count / latest_videos：V5 已补列解决
"""
import time
from storage.db import get_business_repository


def _repository():
    repository = get_business_repository()
    if repository is None:
        raise RuntimeError('PostgreSQL business repository is not configured')
    return repository


def get_latest_batch_ts():
    """返回最新批次 ts，无数据返回 None"""
    return _repository().latest_up_observation_ts()


def get_play_ranking(ts, limit=10):
    """从 up_obs 读播放量排行（按 play_rank 升序），JOIN ups 拿 name/face

    V3 后 video_count_total 列已补齐，可完整对应 play_ranking.video_count。
    """
    rows = sorted(
        _repository().up_observation_rows(ts),
        key=lambda row: row['payload'].get('play_rank', 0),
    )
    rows = [row for row in rows if row['payload'].get('play_rank', 0) > 0][:limit]
    return [{
        'mid': row['mid'], 'name': row['name'] or '', 'face': row['face'] or '',
        'total_recent_views': row['payload'].get('total_recent_views'),
        'avg_views': row['payload'].get('avg_views'),
        'video_count': row['payload'].get('video_count'),
        'follower_count': row['payload'].get('follower_count'),
        'kichu_video_count': row['payload'].get('kichu_video_count'),
        'latest_pub_date': row['payload'].get('latest_pub_date'),
    } for row in rows]


def get_creator_ranking(ts, limit=10):
    """从 up_obs 读活跃度排行（按 activity_rank 升序），JOIN ups 拿 name/face

    creator_ranking 的所有字段都能在 up_obs 找到对应，可完整切读。
    """
    rows = sorted(
        _repository().up_observation_rows(ts),
        key=lambda row: row['payload'].get('activity_rank', 0),
    )
    rows = [row for row in rows if row['payload'].get('activity_rank', 0) > 0][:limit]
    return [{
        'mid': row['mid'], 'name': row['name'] or '', 'face': row['face'] or '',
        'recent_video_count': row['payload'].get('recent_video_count'),
        'total_recent_views': row['payload'].get('total_recent_views'),
        'avg_views': row['payload'].get('avg_views'),
        'follower_count': row['payload'].get('follower_count'),
        'kichu_video_count': row['payload'].get('kichu_video_count'),
        'latest_pub_date': row['payload'].get('latest_pub_date'),
    } for row in rows]


# ==================== summary + up_details ====================

def get_summary(ts, now=None):
    """从 up_obs 聚合算出 summary

    可完整覆盖的字段：
      total_ups / total_views / kichu_up_count / active_up_count

    已知近似缺口：
      total_videos：用 SUM(video_count_30d) 近30天发布数
      kichu_video_count：用 SUM(kichu_count_30d) 近30天鬼畜视频数（V6 补列，与 total_videos 同数据源）
      avg_views_per_video：由 total_views / total_videos 派生

    参数:
      ts: 批次时刻
      now: 当前时刻（默认 time.time()），用于 active_up_count 的 7 天 cutoff
    """
    now = now or int(time.time())
    week_ago = now - 7 * 86400
    payloads = [row['payload'] for row in _repository().up_observation_rows(ts)]
    total_videos = sum(payload.get('recent_video_count') or 0 for payload in payloads)
    total_views = sum(payload.get('total_recent_views') or 0 for payload in payloads)
    kichu = sum(payload.get('recent_kichu_count') or 0 for payload in payloads)
    if kichu == 0:
        kichu = min(sum(payload.get('kichu_video_count') or 0 for payload in payloads), total_videos)
    return {
        'total_ups': len(payloads),
        'total_videos': total_videos,
        'total_views': total_views,
        'avg_views_per_video': int(total_views / total_videos) if total_videos else 0,
        'kichu_up_count': sum(1 for payload in payloads if (payload.get('kichu_video_count') or 0) > 0),
        'kichu_video_count': kichu,
        'active_up_count': sum(1 for payload in payloads if (payload.get('latest_pub_date') or 0) > week_ago),
    }


def get_up_details(ts):
    """从 up_obs 读全量 UP 列表（对应 up_details）

    V5 后所有字段完整覆盖（sign/following_count/latest_videos 已补列）：
      mid / name / face / sign / follower_count / following_count /
      latest_videos / kichu_video_count / total_recent_views / latest_pub_date /
      avg_views / video_count / recent_video_count
    """
    rows = sorted(
        _repository().up_observation_rows(ts),
        key=lambda row: row['payload'].get('latest_pub_date') or 0,
        reverse=True,
    )
    return [{
        'mid': row['mid'], 'name': row['name'] or '', 'face': row['face'] or '',
        'sign': row['payload'].get('sign') or '',
        'follower_count': row['payload'].get('follower_count'),
        'following_count': row['payload'].get('following_count') or 0,
        'latest_videos': row['payload'].get('latest_videos') or [],
        'kichu_video_count': row['payload'].get('kichu_video_count'),
        'total_recent_views': row['payload'].get('total_recent_views'),
        'latest_pub_date': row['payload'].get('latest_pub_date'),
        'avg_views': row['payload'].get('avg_views'),
        'video_count': row['payload'].get('video_count'),
        'recent_video_count': row['payload'].get('recent_video_count'),
    } for row in rows]
