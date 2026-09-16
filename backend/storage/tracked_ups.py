"""UP主动态 — 名单管理 + 配置存储 + 追踪申请审核

本模块管理 tracked_ups.json（名单 + 配置 + 访客申请）。
"""
import json
import os
import secrets
import time
import threading
from datetime import datetime, timezone, timedelta

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
TRACKED_FILE = os.path.join(DATA_DIR, 'tracked_ups.json')

DEFAULT_CONFIG = {}

# tracked_ups.json 读写锁：Flask threaded=True 下保护 read-modify-write 全程
# （save_tracked_list / save_config 都是 RMW，无锁会丢更新）
_tracked_lock = threading.Lock()
_state_repository = None


def configure_state_repository(repository):
    """Install the PostgreSQL tracked-UP state repository for public adapters."""
    global _state_repository
    _state_repository = repository


# ==================== 文件工具 ====================

def _ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def _safe_read_json(filepath, default=None):
    if not os.path.exists(filepath):
        return default
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return default


def _safe_write_json(filepath, data):
    """原子写：先写 .tmp 再 os.replace 覆盖。

    关键修复（V1 灯下黑）：原 open('w') 是截断式非原子写，写到一半被另一请求
    读到会变成半截 JSON，_safe_read_json except 后返回 default {}，导致整段
    ups/config 被空值覆盖。atomic write + 调用方持锁 = 双保险。

    Windows 特性：os.replace 若目标文件正被另一句柄打开会抛 PermissionError。
    生产中读路径 _tracked_lock 与写互斥（见 load_tracked_list/load_config），
    不会长时间持锁；此处再加重试兜底瞬时占用（如外部工具、杀毒扫描）。
    """
    _ensure_dir(os.path.dirname(filepath))
    tmp_path = filepath + '.tmp'
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    # Windows 上 os.replace 是原子的（跨文件系统则不是，但 .tmp 与目标同目录无此问题）
    # 重试兜底：目标被瞬时占用（外部进程/杀毒）的边缘情况
    last_err = None
    for attempt in range(5):
        try:
            os.replace(tmp_path, filepath)
            return
        except PermissionError as e:
            last_err = e
            time.sleep(0.01 * (attempt + 1))   # 10/20/30/40/50ms
    # 重试耗尽仍失败：抛出，调用方需感知（事务会回滚，不会留下半截 JSON）
    raise last_err


# ==================== 配置 ====================

def load_config():
    """读配置（持锁，与写互斥）。

    持锁原因：_safe_write_json 内部 os.replace 在 Windows 上要求目标文件
    没有被打开的句柄，若无读锁，load_config 正在 open() 的瞬间 save 写入会
    PermissionError。读写都持 _tracked_lock = 互斥简单可靠（tracked_ups.json
    读写频次极低，互斥无性能影响）。
    """
    if _state_repository is not None:
        tracked = _state_repository.load_tracked_list()
        return {**DEFAULT_CONFIG, **(tracked or {}).get('config', {})}
    with _tracked_lock:
        tracked = _safe_read_json(TRACKED_FILE)
    if tracked and 'config' in tracked:
        return {**DEFAULT_CONFIG, **tracked['config']}
    return dict(DEFAULT_CONFIG)


def save_config(config):
    """保存配置（持锁 RMW，防丢更新）。

    关键修复：原为 read→modify→write 无锁，与 save_tracked_list 并发时会
    互相覆盖（A 写完 ups、B 读到旧 ups、B 写回旧 ups + 新 config → A 的 ups 丢失）。
    _tracked_lock 保护整个 RMW，原子写防止半写读脏。
    """
    if _state_repository is not None:
        _state_repository.save_tracked_config({**DEFAULT_CONFIG, **config}, int(time.time()))
        return
    with _tracked_lock:
        tracked = _safe_read_json(TRACKED_FILE, {})
        tracked['config'] = {**DEFAULT_CONFIG, **config}
        _safe_write_json(TRACKED_FILE, tracked)


# ==================== 名单管理 ====================

def load_tracked_list():
    """返回 {'ups': [...], 'config': {...}, 'updated_at': int}（持锁读）"""
    if _state_repository is not None:
        return _state_repository.load_tracked_list()
    with _tracked_lock:
        tracked = _safe_read_json(TRACKED_FILE, {})
    if not tracked:
        return None
    return {
        'ups': tracked.get('ups', []),
        'config': {**DEFAULT_CONFIG, **tracked.get('config', {})},
        'updated_at': tracked.get('updated_at', 0),
    }


def save_tracked_list(ups, updated_at=None):
    """保存名单（持锁 RMW，防丢更新）。

    关键修复：原 read→modify→write 无锁，import 与 save_list 并发会丢更新；
    且 _safe_write_json 原非原子，并发读取会拿到半截 JSON 经 except 退化为 {}，
    导致整段 ups 或 config 被空值覆盖。_tracked_lock + 原子写 = 双保险。
    """
    if _state_repository is not None:
        current = _state_repository.load_tracked_list() or {}
        _state_repository.save_tracked_list(
            ups, updated_at or int(time.time()), current.get('config', DEFAULT_CONFIG),
        )
        return
    with _tracked_lock:
        tracked = _safe_read_json(TRACKED_FILE, {})
        tracked['ups'] = ups
        if updated_at:
            tracked['updated_at'] = updated_at
        else:
            tracked['updated_at'] = int(time.time())
        if 'config' not in tracked:
            tracked['config'] = dict(DEFAULT_CONFIG)
        _safe_write_json(TRACKED_FILE, tracked)


def has_tracked_list():
    """是否已配置名单。

    tracked_ups.json 有 ups → True；
    若 tracked_ups.json 被意外清空（历史 bug 或保存时传了空数组），
    但 up_obs 表有历史分析数据，也视为已配置——避免用户进看板被强制跳配置页、
    看不到上次分析数据。
    """
    tracked = _safe_read_json(TRACKED_FILE)
    if tracked and len(tracked.get('ups', [])) > 0:
        return True
    # 兜底：查 up_obs 是否有数据
    try:
        from storage.db import get_conn
        row = get_conn().execute('SELECT 1 FROM up_obs LIMIT 1').fetchone()
        return row is not None
    except Exception:
        return False


def diff_mutual_list(existing_ups, fresh_mutuals):
    """
    增量对比：已有名单 vs 最新互粉列表
    fresh_mutuals: [{'mid': ..., 'name': ..., 'face': ..., ...}, ...]
    返回:
      - added: 新互粉（不在名单中）
      - removed: 已取关（在名单中但不在新互粉列表中）
      - unchanged: 仍在互粉且已在名单中
    """
    existing_mids = {u['mid'] for u in existing_ups}
    fresh_mids = {u['mid'] for u in fresh_mutuals}

    existing_by_mid = {u['mid']: u for u in existing_ups}
    fresh_by_mid = {u['mid']: u for u in fresh_mutuals}

    added = []
    for mid in fresh_mids - existing_mids:
        added.append(fresh_by_mid[mid])

    removed = []
    for mid in existing_mids - fresh_mids:
        removed.append(existing_by_mid[mid])

    unchanged = []
    for mid in existing_mids & fresh_mids:
        u = dict(existing_by_mid[mid])
        # 更新昵称和头像（可能变了）
        u['name'] = fresh_by_mid[mid].get('name', u['name'])
        u['face'] = fresh_by_mid[mid].get('face', u['face'])
        unchanged.append(u)

    return {'added': added, 'removed': removed, 'unchanged': unchanged}


# ==================== UP 追踪申请（访客提交 / 站长审核）====================
# 方案C（公网多用户）：访客申请追踪UP → 站长审核入池。与 ups/config 同文件同锁同原子写。

REQUESTS_PENDING_LIMIT = 50      # 全局待审核队列上限（防堆积）
REQUESTS_PROCESSED_KEEP = 100    # 已处理单滚动保留条数
REQUESTS_DAILY_LIMIT = 3         # 每访客每日提交上限
TRACK_POOL_LIMIT = 300           # 追踪池软上限（现为203，留增长空间）

CN_TZ = timezone(timedelta(hours=8))


def _day_key(ts):
    """epoch 秒 → CN 时区日期键（日限计数用）"""
    return datetime.fromtimestamp(ts or 0, CN_TZ).strftime('%Y-%m-%d')


def _requests_state(tracked):
    """归一化 requests 段（旧文件无此段/结构异常时补默认，不抛异常）"""
    reqs = tracked.get('requests')
    if not isinstance(reqs, dict):
        reqs = {}
    if not isinstance(reqs.get('pending'), list):
        reqs['pending'] = []
    if not isinstance(reqs.get('processed'), list):
        reqs['processed'] = []
    return reqs


def _push_processed(reqs, item):
    """已处理单入列（新的在前）+ 滚动截断"""
    reqs['processed'].insert(0, item)
    del reqs['processed'][REQUESTS_PROCESSED_KEEP:]


def add_up_request(mid, snapshot, reason, visitor_id, request_type='add'):
    """访客提交追踪申请（单锁事务，全部校验+写入一次完成）。

    返回 (request_dict, None) 或 (None, error_code)：
      ALREADY_TRACKED  mid 已在追踪池
      POOL_FULL        追踪池达软上限
      DUPLICATE        同 mid 已有待审核申请
      QUEUE_FULL       全局待审核队列已满
      DAILY_LIMIT      该访客今日提交数达上限
    """
    if _state_repository is not None:
        if request_type != 'add':
            return None, 'INVALID_TYPE'
        try:
            request_id = _state_repository.create_tracking_request(
                int(mid), visitor_id, snapshot or {}, reason, int(time.time()),
            )
        except (TypeError, ValueError):
            return None, 'INVALID_TYPE'
        return {
            'id': request_id, 'mid': mid, 'request_type': request_type, 'up': snapshot,
            'reason': reason, 'visitor_id': visitor_id, 'submitted_at': int(time.time()),
            'status': 'pending',
        }, None
    with _tracked_lock:
        tracked = _safe_read_json(TRACKED_FILE, {})
        reqs = _requests_state(tracked)
        pool = tracked.get('ups') or []

        if request_type not in ('add', 'remove'):
            return None, 'INVALID_TYPE'
        active = any(u.get('mid') == mid and u.get('enabled', True) for u in pool)
        if request_type == 'remove' and not active:
            return None, 'NOT_TRACKED'
        if request_type == 'remove' and not reason.strip():
            return None, 'REASON_REQUIRED'
        if request_type == 'add' and active:
            return None, 'ALREADY_TRACKED'
        if request_type == 'add' and sum(u.get('enabled', True) for u in pool) >= TRACK_POOL_LIMIT:
            return None, 'POOL_FULL'
        if any(r.get('mid') == mid for r in reqs['pending']):
            return None, 'DUPLICATE'
        if len(reqs['pending']) >= REQUESTS_PENDING_LIMIT:
            return None, 'QUEUE_FULL'

        today = _day_key(time.time())
        mine_today = sum(
            1 for r in reqs['pending'] + reqs['processed']
            if r.get('visitor_id') == visitor_id and _day_key(r.get('submitted_at', 0)) == today
        )
        if mine_today >= REQUESTS_DAILY_LIMIT:
            return None, 'DAILY_LIMIT'

        req = {
            # 时间戳+4位随机：规避收藏同秒重号问题（同秒不同访客不撞id）
            'id': f'req_{int(time.time())}_{secrets.token_hex(2)}',
            'mid': mid,
            'request_type': request_type,
            'up': snapshot,            # 提交时快照（审核页免开B站）
            'reason': reason,
            'visitor_id': visitor_id,
            'submitted_at': int(time.time()),
            'status': 'pending',
        }
        reqs['pending'].append(req)
        tracked['requests'] = reqs
        _safe_write_json(TRACKED_FILE, tracked)
        return req, None


def get_my_up_requests(visitor_id):
    """访客查自己的申请（pending + processed）"""
    with _tracked_lock:
        tracked = _safe_read_json(TRACKED_FILE, {})
    reqs = _requests_state(tracked)
    return {
        'pending': [r for r in reqs['pending'] if r.get('visitor_id') == visitor_id],
        'processed': [r for r in reqs['processed'] if r.get('visitor_id') == visitor_id],
    }


def withdraw_up_request(req_id, visitor_id):
    """访客撤回自己的待审核申请。

    返回 None（成功）或 error_code：
      NOT_OWNER  不是本人的申请
      NOT_FOUND  申请不存在（含已审核/已撤回——不在 pending 里）
    """
    with _tracked_lock:
        tracked = _safe_read_json(TRACKED_FILE, {})
        reqs = _requests_state(tracked)
        for i, r in enumerate(reqs['pending']):
            if r.get('id') == req_id:
                if r.get('visitor_id') != visitor_id:
                    return 'NOT_OWNER'
                out = dict(r)
                out['status'] = 'withdrawn'
                out['reviewed_at'] = int(time.time())
                reqs['pending'].pop(i)
                _push_processed(reqs, out)
                tracked['requests'] = reqs
                _safe_write_json(TRACKED_FILE, tracked)
                return None
        return 'NOT_FOUND'


def list_all_up_requests():
    """站长审核视图：全部队列 + 最近已处理"""
    with _tracked_lock:
        tracked = _safe_read_json(TRACKED_FILE, {})
    reqs = _requests_state(tracked)
    return {
        'pending': reqs['pending'],
        'processed': reqs['processed'][:50],
        'pending_count': len(reqs['pending']),
    }


def review_up_request(req_id, action, reject_reason=None):
    """站长审核（单锁事务：状态流转 + 同mid联动 + 名单写入一次完成）。

    action='approve'：
      - 单子 → processed(approved)；同 mid 其他 pending → superseded
      - mid 不在池 → ups 追加 {mid,name,face,added_at,enabled}（added_to_pool=True）
      - mid 已在池（审核前被手动导入）→ 幂等通过，不重复添加
    action='reject'：
      - 单子 → processed(rejected + reject_reason)

    返回 (result_dict, None) 或 (None, error_code)：NOT_FOUND
    """
    if _state_repository is not None:
        if action not in ('approve', 'reject'):
            return None, 'NOT_FOUND'
        try:
            result = _state_repository.review_tracking_request(req_id, action, int(time.time()))
        except LookupError:
            return None, 'NOT_FOUND'
        return result, None
    with _tracked_lock:
        tracked = _safe_read_json(TRACKED_FILE, {})
        reqs = _requests_state(tracked)

        target = None
        for i, r in enumerate(reqs['pending']):
            if r.get('id') == req_id:
                target = (i, r)
                break
        if target is None:
            return None, 'NOT_FOUND'
        i, r = target
        now = int(time.time())
        out = dict(r)

        if action == 'approve':
            pool = tracked.get('ups') or []
            existing = next((u for u in pool if u.get('mid') == r['mid']), None)
            removing = r.get('request_type', 'add') == 'remove'
            already = bool(existing and existing.get('enabled', True))
            if not removing and not already and sum(u.get('enabled', True) for u in pool) >= TRACK_POOL_LIMIT:
                return None, 'POOL_FULL'
            pool_up = None
            if removing:
                if existing:
                    existing['enabled'] = False
                    existing['disabled_at'] = now
            elif existing:
                existing['enabled'] = True
                existing.pop('disabled_at', None)
                pool_up = existing
            else:
                up = r.get('up') or {}
                pool_up = {
                    'mid': r['mid'],
                    'name': up.get('name', ''),
                    'face': up.get('face', ''),
                    'added_at': now,          # 供日历增量回填识别新UP
                    'enabled': True,
                }
                pool.append(pool_up)
            tracked['ups'] = pool
            tracked['updated_at'] = now
            out['status'] = 'approved'
            out['reviewed_at'] = now
            if already and not removing:
                out['note'] = '审核前已在追踪名单中，未重复添加'
            # 同 mid 其他 pending → superseded，一并移入 processed（审核列表 pending 清空）
            superseded = []
            remaining = []
            for j, other in enumerate(reqs['pending']):
                if j != i and other.get('mid') == r['mid']:
                    o = dict(other)
                    o['status'] = 'superseded'
                    o['reviewed_at'] = now
                    superseded.append(o)
                elif j != i:
                    remaining.append(other)
            reqs['pending'] = remaining
            _push_processed(reqs, out)
            for o in superseded:
                _push_processed(reqs, o)
            tracked['requests'] = reqs
            _safe_write_json(TRACKED_FILE, tracked)
            return {'request': out, 'added_to_pool': not removing and not already,
                    'removed_from_pool': removing and already, 'pool_up': pool_up}, None

        # reject
        out['status'] = 'rejected'
        out['reviewed_at'] = now
        out['reject_reason'] = reject_reason or ''
        reqs['pending'].pop(i)
        _push_processed(reqs, out)
        tracked['requests'] = reqs
        _safe_write_json(TRACKED_FILE, tracked)
        return {'request': out, 'added_to_pool': False}, None
