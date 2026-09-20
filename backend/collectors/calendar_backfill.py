"""发布日历回填 — 遍历追踪 UP，可靠拉取投稿并写入日历。

请求失败会抛出 CalendarFetchError，绝不再与“成功但无投稿”共用空列表语义。
"""
import time
import random
from datetime import datetime, timezone, timedelta

from collectors.bilibili_auth import get_cookie_str, get_headers, safe_get_with_wbi
from storage.db import upsert_calendar_videos, reconcile_calendar_author, get_up_names
from storage.tracked_ups import load_tracked_list

CN_TZ = timezone(timedelta(hours=8))

# 默认目标年份只用于兼容旧调用；路由/任务必须显式传 year。
TARGET_YEAR = datetime.now(CN_TZ).year
# 增量回填默认窗口（天）：只抓最近 N 天视频，兼顾完整性与速度。
# 日历热力图全年显示，但播放量是回填快照，老视频靠窗口内增量刷新，窗口外保持历史快照。
DEFAULT_RECENT_DAYS = 30
# 每页抓取数量
PAGE_SIZE = 50
# API 请求间隔（秒）
REQUEST_DELAY = 0.35
UP_RETRY_ATTEMPTS = 2


class FetchedVideos(list):
    """保持 list 向后兼容，同时携带完整分页元数据。"""

    def __init__(self, values=(), pages=0):
        super().__init__(values)
        self.pages = pages
        self.complete = True


class CalendarFetchError(RuntimeError):
    """单个 UP 抓取未完整完成；partial_videos 可安全追加，但不可触发删除对账。"""

    def __init__(self, code, message, partial_videos=None, pages=0):
        super().__init__(message)
        self.code = code
        self.partial_videos = list(partial_videos or [])
        self.pages = pages


def _fmt_date(pub_ts):
    """epoch → 'MM-DD' 字符串"""
    dt = datetime.fromtimestamp(pub_ts, tz=CN_TZ)
    return dt.strftime('%m-%d')


def _is_target_year(pub_ts, year=None):
    """判断是否为目标年份的投稿。"""
    if not pub_ts:
        return False
    return datetime.fromtimestamp(pub_ts, tz=CN_TZ).year == (year or TARGET_YEAR)


def fetch_up_videos_by_year(mid, year=TARGET_YEAR, recent_days=None):
    """拉取一个 UP 主指定年份/最近 N 天的投稿

    按 pubdate 降序逐页翻取：
      - recent_days=None（默认）：年份模式，翻到非目标年份视频停止
      - recent_days=N：窗口模式，翻到早于 (now - N 天) 的视频停止（降序排列，之后只会更早）

    成功返回 FetchedVideos；接口/Cookie/网络异常抛出 CalendarFetchError。
    """
    url = 'https://api.bilibili.com/x/space/wbi/arc/search'
    all_videos = []
    pn = 1
    seen_years = set()
    cutoff_ts = int(time.time()) - recent_days * 86400 if recent_days else None

    while True:
        params = {'mid': mid, 'pn': pn, 'ps': PAGE_SIZE, 'order': 'pubdate', 'tid': 0}
        data = safe_get_with_wbi(url, params)

        if not data:
            code = 'collector_auth_missing' if not get_cookie_str() else 'request_failed'
            message = '采集账号未登录' if code == 'collector_auth_missing' else 'B站请求失败'
            raise CalendarFetchError(code, message, all_videos, pages=pn - 1)
        if data.get('error'):
            raise CalendarFetchError(
                str(data.get('error')),
                data.get('message') or 'B站接口返回错误',
                all_videos,
                pages=pn - 1,
            )

        vlist = data.get('data', {}).get('list', {}).get('vlist', [])
        if not vlist:
            break

        # 收集视频，直到遇到窗口外/非目标年份的视频
        page_has_target = False
        early_stop = False
        for v in vlist:
            pub_ts = v.get('created', 0)
            if not pub_ts:
                continue

            if cutoff_ts is not None:
                # 窗口模式：按 pubdate 降序，遇到早于窗口的视频 → 结束（后续只会更早）
                if pub_ts < cutoff_ts:
                    early_stop = True
                    break
                page_has_target = True
                all_videos.append({
                    'bvid': v.get('bvid', ''),
                    'mid': mid,
                    'pub_date': pub_ts,
                    'pub_date_str': _fmt_date(pub_ts),
                    'views': v.get('play', 0),
                    'title': v.get('title', ''),
                })
                continue

            pub_year = datetime.fromtimestamp(pub_ts, tz=CN_TZ).year
            seen_years.add(pub_year)

            if pub_year == year:
                page_has_target = True
                all_videos.append({
                    'bvid': v.get('bvid', ''),
                    'mid': mid,
                    'pub_date': pub_ts,
                    'pub_date_str': _fmt_date(pub_ts),
                    'views': v.get('play', 0),
                    'title': v.get('title', ''),
                })
            elif pub_year < year:
                # 已经翻到早于目标年的视频，停止
                if not page_has_target:
                    return FetchedVideos(all_videos, pages=pn)
                early_stop = True
                break

        if early_stop:
            break

        # 年份模式：当前页没有目标年份的视频，且已出现了更老的年份 → 结束
        if cutoff_ts is None and not page_has_target and any(y < year for y in seen_years):
            break

        # 如果列表长度小于 PAGE_SIZE，说明没有更多页
        if len(vlist) < PAGE_SIZE:
            break

        pn += 1
        time.sleep(REQUEST_DELAY)

    return FetchedVideos(all_videos, pages=pn)


def backfill_calendar(mids=None, recent_days=None, year=None, progress_callback=None):
    """回填日历数据（首次全量，或增量补抓）

    参数:
      mids: 要回填的 UP mid 列表，None = 全量（从 tracked_ups 读取，只含 enabled=True）
      recent_days: 增量窗口（天），None = 全年；给定 N 则只抓最近 N 天投稿

    progress_callback 可接收单 UP 状态字典；返回包含成功/空/部分/失败的完整统计。
    """
    target_year = int(year or datetime.now(CN_TZ).year)
    if mids is None:
        tracked = load_tracked_list()
        ups = tracked.get('ups', []) if tracked else []
        # 日历只统计启用观测的 UP（disabled 的已退出观测，历史数据不再展示）
        ups = [u for u in ups if u.get('enabled', True)]
    else:
        # 增量模式：只处理指定 mids
        names = get_up_names(mids)
        ups = [{'mid': mid, 'name': names.get(int(mid)) or f'UID:{mid}'} for mid in mids]

    if not ups:
        print('没有需要回填的 UP 主')
        return {
            'status': 'succeeded', 'total_videos': 0, 'total_ups': 0,
            'processed_ups': 0, 'success_ups': 0, 'empty_ups': 0,
            'partial_ups': 0, 'failed_ups': 0, 'elapsed': 0, 'errors': [],
        }

    mode = f'最近 {recent_days} 天' if recent_days else target_year
    print(f'开始回填 {len(ups)} 个 UP 主的 {mode} 投稿...')
    start_time = time.time()
    total_videos = 0
    success_ups = 0
    empty_ups = 0
    failed_ups = 0
    partial_ups = 0
    processed_ups = 0
    errors = []
    write_totals = {'inserted': 0, 'updated': 0, 'unchanged': 0, 'invalid': 0}
    tracked_mids = [u['mid'] for u in ups]

    for i, up in enumerate(ups):
        mid = up['mid']
        name = up.get('name', f'UID:{mid}')
        print(f'  [{i+1}/{len(ups)}] {name} (UID: {mid})...', end=' ')

        if progress_callback:
            progress_callback({'mid': mid, 'name': name, 'status': 'running'})

        fetch_error = None
        videos = None
        attempts = 0
        for attempts in range(1, UP_RETRY_ATTEMPTS + 1):
            try:
                videos = fetch_up_videos_by_year(mid, target_year, recent_days=recent_days)
                fetch_error = None
                break
            except CalendarFetchError as exc:
                fetch_error = exc
                # 鉴权错误重试没有意义；其他错误做带抖动的指数退避。
                if exc.code in ('collector_auth_missing', 'cookie_expired'):
                    break
                if attempts < UP_RETRY_ATTEMPTS:
                    time.sleep((0.75 * (2 ** (attempts - 1))) + random.uniform(0, 0.25))
            except Exception as exc:
                fetch_error = CalendarFetchError('unexpected_error', str(exc))
                break

        item_status = 'success'
        pages = getattr(videos, 'pages', 0) if videos is not None else getattr(fetch_error, 'pages', 0)
        item_videos = 0
        if fetch_error is not None:
            partial = fetch_error.partial_videos
            if partial:
                stats = upsert_calendar_videos(partial, tracked_mids=tracked_mids)
                item_videos = stats['valid']
                total_videos += stats['valid']
                for key in write_totals:
                    write_totals[key] += stats[key]
                partial_ups += 1
                item_status = 'partial'
            else:
                failed_ups += 1
                item_status = 'failed'
            error_info = {
                'mid': mid, 'name': name, 'code': fetch_error.code,
                'message': str(fetch_error), 'pages': pages,
            }
            errors.append(error_info)
            print(f'{item_status}: {fetch_error.code} {fetch_error}')
        else:
            if videos:
                stats = upsert_calendar_videos(videos, tracked_mids=tracked_mids)
                item_videos = stats['valid']
                total_videos += stats['valid']
                for key in write_totals:
                    write_totals[key] += stats[key]
                print(f"{stats['valid']} 条视频（新增 {stats['inserted']} / 更新 {stats['updated']}）")
            else:
                empty_ups += 1
                item_status = 'empty'
                print('无投稿')
            # 只有完整年份扫描成功，才允许推进软失效计数。
            if recent_days is None:
                reconcile_calendar_author(mid, target_year, [v['bvid'] for v in videos])
            success_ups += 1

        processed_ups += 1
        if progress_callback:
            progress_callback({
                'mid': mid, 'name': name, 'status': item_status,
                'pages': pages, 'videos': item_videos, 'attempts': attempts,
                'error_code': fetch_error.code if fetch_error else '',
                'error_message': str(fetch_error) if fetch_error else '',
            })

        # 控制请求频率（每 UP 之间有额外间隔）
        if i < len(ups) - 1:
            time.sleep(REQUEST_DELAY)

    elapsed = int(time.time() - start_time)
    status = 'succeeded'
    if failed_ups or partial_ups:
        status = 'partial' if success_ups or partial_ups else 'failed'
    print(f'回填完成: {total_videos} 条视频, 成功 {success_ups}, 部分 {partial_ups}, 失败 {failed_ups}, 耗时 {elapsed}s')
    return {
        'status': status,
        'total_videos': total_videos,
        'total_ups': len(ups),
        'processed_ups': processed_ups,
        'success_ups': success_ups,
        'empty_ups': empty_ups,
        'partial_ups': partial_ups,
        'failed_ups': failed_ups,
        'elapsed': elapsed,
        'write_stats': write_totals,
        'errors': errors,
    }


def backfill_single_up(mid, year=None):
    """增量回填单个 UP（新增 UP 时调用）"""
    target_year = int(year or datetime.now(CN_TZ).year)
    print(f'补抓 UP {mid} 的 {target_year} 年投稿...')
    videos = fetch_up_videos_by_year(mid, target_year)
    if videos:
        stats = upsert_calendar_videos(videos, tracked_mids=[mid])
        reconcile_calendar_author(mid, target_year, [v['bvid'] for v in videos])
        print(f"  写入 {stats['valid']} 条视频")
        return stats['valid']
    reconcile_calendar_author(mid, target_year, [])
    print('  无投稿')
    return 0
