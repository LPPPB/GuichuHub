"""Versioned video portraits. No database, clock, page ranking, or prediction."""
from bisect import bisect_left, bisect_right
import math

ALGORITHM = 'radar-v2'
MIN_REFERENCE = 200
AGE_EDGES = (0, 1, 3, 7, 14, 30, math.inf)
COUNTS = ('views', 'likes', 'coins', 'favorites', 'comments', 'danmaku', 'shares')
METRICS = ('views', 'likes_rate', 'coins_rate', 'favorites_rate', 'comments_rate', 'danmaku_rate', 'shares_rate', 'speed')
AXES = (
    ('reach', '播放规模', ('views',)),
    ('approval', '观众认可', ('likes_rate', 'coins_rate')),
    ('retention', '收藏倾向', ('favorites_rate',)),
    ('discussion', '讨论活跃', ('comments_rate', 'danmaku_rate')),
    ('sharing', '分享倾向', ('shares_rate',)),
    ('growth', '近期增速', ('speed',)),
)
LABELS = dict(views='播放', likes_rate='点赞', coins_rate='投币', favorites_rate='收藏',
              comments_rate='评论', danmaku_rate='弹幕', shares_rate='分享', speed='播放增速')


def number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        n = float(value)
        return n if math.isfinite(n) and n >= 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def percentile_position(value, values):
    if value == 0:
        return 0.0
    return round(100 * (bisect_left(values, value) + bisect_right(values, value)) / (2*len(values)), 1)


def _latest(context, now):
    row = context.get('latest')
    if not row:
        return None, 'unavailable', '暂无可信观测'
    if row.get('metrics_source') != 'bilibili_stat':
        return None, 'unavailable', '数据来源未验证'
    ts = number(row.get('observed_at'))
    if not ts or ts > now or any(number(row.get(k)) is None for k in COUNTS):
        return None, 'invalid', '观测字段或时间无效'
    return {**row, **{k: number(row[k]) for k in COUNTS}, 'observed_at': ts}, 'available', None


def _age(context, row):
    pub = number(context.get('pub_date'))
    if not pub or pub > row['observed_at']:
        return None
    days = (row['observed_at'] - pub) / 86400
    return min(5, bisect_right(AGE_EDGES, days)-1)


def _growth(context, row):
    end = number(row.get('observed_at'))
    candidates = []
    for p in context.get('history', []):
        ts, views = number(p.get('observed_at')), number(p.get('views'))
        if p.get('metrics_source') == 'bilibili_stat' and ts and views is not None:
            gap = end-ts
            if 5*3600 <= gap <= 7*3600:
                candidates.append((abs(gap-21600), ts, views))
    if not candidates:
        return None, 'unavailable', '观测不足', None, None
    _, start, views = min(candidates)
    delta = float(row['views'])-views
    hours = (end-start)/3600
    if delta < 0:
        return None, 'invalid', '播放计数下降', hours, delta
    return delta/hours, 'available', None, hours, delta


def _values(context, row):
    views = number(row['views'])
    values = {'views': views}
    if views >= 1500:
        for key in COUNTS[1:]:
            values[key+'_rate'] = float(row[key])/views*1000
    speed, _, _, _, _ = _growth(context, row)
    if speed is not None:
        values['speed'] = speed
    return values


def _distribution(values, cohorts):
    ordered = sorted(values)
    status = ('insufficient_baseline' if len(ordered) < MIN_REFERENCE else
              'invalid' if ordered[0] == ordered[-1] else 'available')
    return dict(values=ordered, count=len(ordered), status=status, cohorts=cohorts,
                age_min_days=AGE_EDGES[min(cohorts)] if cohorts else None,
                age_max_days=(None if cohorts and max(cohorts) == 5 else
                              AGE_EDGES[max(cohorts)+1] if cohorts else None))


def build_baseline(contexts, cutoff_ts, valid_until):
    unique = {}
    for c in contexts:
        row, _, _ = _latest(c, cutoff_ts)
        if row and row['observed_at'] >= cutoff_ts-30*86400 and c.get('bvid'):
            old = unique.get(c['bvid'])
            if not old or row['observed_at'] > old['latest']['observed_at']:
                unique[c['bvid']] = {**c, 'latest': row}
    samples = [(c, c['latest'], _age(c, c['latest'])) for c in unique.values()]
    distributions = {}
    for metric in METRICS:
        groups = [{'cohorts': [i], 'values': []} for i in range(6)]
        global_values = []
        for c, row, age in samples:
            value = _values(c, row).get(metric)
            if value is None:
                continue
            global_values.append(value)
            if age is not None:
                groups[age]['values'].append(value)
        if metric == 'views':
            distributions[metric] = [_distribution(global_values, [])]
            continue
        while len(groups) > 1:
            small = next((i for i, g in enumerate(groups) if len(g['values']) < MIN_REFERENCE), None)
            if small is None:
                break
            neighbor = small-1 if small else 1
            lo, hi = sorted((small, neighbor))
            groups[lo] = dict(cohorts=groups[lo]['cohorts']+groups[hi]['cohorts'],
                              values=groups[lo]['values']+groups[hi]['values'])
            groups.pop(hi)
        distributions[metric] = [_distribution(g['values'], g['cohorts']) for g in groups]
    return dict(algorithm_version=ALGORITHM, version=f'{ALGORITHM}-{cutoff_ts}', cutoff_ts=cutoff_ts,
                valid_until=valid_until, sample_count=len(unique), distributions=distributions)


def _score(metric, value, age, baseline, now):
    if not baseline or baseline.get('algorithm_version') != ALGORITHM:
        return None, 'insufficient_baseline', '参考样本不足', None
    if baseline.get('valid_until', 0) <= now:
        return None, 'insufficient_baseline', '基线已到期', None
    if metric != 'views' and age is None:
        return None, 'unavailable', '发布时间不可用', None
    groups = baseline['distributions'].get(metric, [])
    group = next((g for g in groups if metric == 'views' or age in g['cohorts']), None)
    if not group or group['status'] == 'insufficient_baseline':
        return None, 'insufficient_baseline', '参考样本不足', None
    reference = {k: v for k, v in group.items() if k != 'values'}
    if group['status'] != 'available':
        return None, 'insufficient_baseline', '基准无区分度', reference
    return percentile_position(value, group['values']), 'available', None, reference


def build_video_radar(context, baseline, now):
    row, row_status, row_reason = _latest(context, now)
    values = _values(context, row) if row else {}
    age = _age(context, row) if row else None
    axes = []
    for axis_id, label, metrics in AXES:
        axis = dict(id=axis_id, label=label, score=None, raw=None, status=row_status,
                    reason=row_reason, unit='播放/小时' if axis_id == 'growth' else
                    '次' if axis_id == 'reach' else '次/千播放', components=[], reference=None)
        if row:
            status, reason = 'available', None
            elapsed = now-row['observed_at']
            if elapsed > (5400 if axis_id == 'growth' else 86400):
                status, reason = 'stale', '观测已过期'
            elif axis_id == 'growth':
                _, status, reason, hours, delta = _growth(context, row)
                axis.update(window_hours=hours, growth_views=delta)
            elif axis_id != 'reach' and float(row['views']) < 1500:
                status, reason = ('unavailable', '播放为零，无法计算比率') if float(row['views']) == 0 else ('low_sample', '样本较少')
            components = []
            for metric in metrics:
                raw = values.get(metric)
                score, child_status, child_reason, reference = (None, status, reason, None)
                if status == 'available' and raw is not None:
                    score, child_status, child_reason, reference = _score(metric, raw, age, baseline, now)
                components.append(dict(id=metric, label=LABELS[metric], raw=raw,
                    score=score, status=child_status, reason=child_reason, reference=reference))
            bad = next((c for c in components if c['status'] != 'available'), None)
            axis.update(components=components, raw=round(components[0]['raw'], 1) if len(metrics) == 1 and components[0]['raw'] is not None else
                        {c['id']: c['raw'] for c in components} if len(metrics) > 1 else None,
                        status=bad['status'] if bad else 'available', reason=bad['reason'] if bad else None,
                        reference=components[0]['reference'])
            if not bad:
                axis['score'] = round(sum(c['score'] for c in components)/len(components), 1)
        axes.append(axis)
    return dict(algorithm_version=ALGORITHM, baseline_version=baseline.get('version') if baseline else None,
                observed_at=row.get('observed_at') if row else None, axes=axes)


def build_online_observation(context, now):
    row = context.get('online') or {}
    count, ts = number(row.get('online_count')), number(row.get('online_observed_at'))
    if count is None or not ts or ts > now:
        return dict(count=None, display=None, precision=None, observed_at=None, status='unavailable')
    precision = row.get('online_precision') or 'unknown'
    display = row.get('online_display')
    if not display:
        display = f'{int(count)}' if precision == 'exact' else f'约{int(count)}'
    return dict(count=int(count), display=display, precision=precision, observed_at=int(ts),
                status='stale' if now-ts > 5400 else 'available')
