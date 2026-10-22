"""鬼畜热度看板 — API 层（四层分离后只剩路由和参数校验）

四层架构（docs/后端架构与演进路线图.md 5.3）：
  crawler/   = 采集层（B站API → 标准化原始观测）
  storage/   = 存储层（PostgreSQL repositories）
  analytics/ = 分析层（热词过滤等）
  jobs/      = 调度层（抓取/观测/UP主动态定时任务）
  app.py     = API层（本文件——只做路由和参数校验）
"""

import sys
import os
import threading
import time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, g, jsonify, request, Response, send_file
from flask_cors import CORS
import requests
from werkzeug.middleware.proxy_fix import ProxyFix

from logger import setup_logging
from config import BACKEND_PORT, get_write_token, ONLINE_BREAK_THRESHOLD, ONLINE_BREAK_COOLDOWN

from storage.database import (
    add_favorite, remove_favorite, update_favorite, get_favorites,
    migrate_legacy_favorites,
)
from collectors.bilibili_auth import (
    generate_qrcode, check_login_status, get_user_info,
    is_logged_in, get_user_info_with_cookie, cookie_dict_to_str,
)
from collectors.bilibili_user import (
    get_all_mutual_followings, get_up_info_by_mid, get_up_relation_stat, search_up_users,
)
from storage.tracked_ups import (
    load_config, save_config,
    load_tracked_list, save_tracked_list, has_tracked_list,
    diff_mutual_list,
    add_up_request, get_my_up_requests, withdraw_up_request,
    list_all_up_requests, review_up_request,
)
from storage.db import register_up, upsert_up_obs
from collectors.bilibili_auth import get_user_info as bili_get_user_info
from storage.auth_store import (
    list_admin_accounts, add_admin_account, remove_admin_account,
    is_admin_mid, update_admin_profile,
    create_session, get_session, delete_session, list_recent_logins,
    request_collector_cookie_update, request_collector_logout,
)

# ── 四层分离导入 ──
from storage.cache import get_data
from analytics.filters import filter_danmaku_words
from jobs.crawl_jobs import get_status, try_acquire_lock, mark_crawling, run_crawl_job, _crawl_job_locked, _crawl_job_live
from jobs.up_trends_jobs import start_analysis, get_progress, get_running_task_id
# 读路径完全走数据库（up_obs + video_obs_snapshot）
from storage.up_trends_reader import load_analysis, load_history_batches
from storage.up_obs_reader import get_latest_batch_ts, get_up_details

DEVELOPMENT_ORIGINS = (
    'http://127.0.0.1:5173',
    'http://localhost:5173',
    'http://127.0.0.1:5174',
    'http://localhost:5174',
)
SESSION_COOKIE_NAME = 'kichu_session'


def _configure_transport_security(flask_app, environ=None):
    """Configure opt-in development CORS and the explicitly trusted proxy hop."""
    environ = os.environ if environ is None else environ
    if str(environ.get('KICHU_ENV', 'production')).strip().lower() == 'development':
        CORS(
            flask_app,
            origins=DEVELOPMENT_ORIGINS,
            supports_credentials=True,
            expose_headers=['Content-Disposition'],
        )
    if str(environ.get('KICHU_TRUST_PROXY', '')).strip() == '1':
        flask_app.wsgi_app = ProxyFix(
            flask_app.wsgi_app,
            x_for=1,
            x_proto=1,
            x_host=1,
        )


app = Flask(__name__)
_configure_transport_security(app)

# ── 写操作访问口令（局域网共享防护）──
# 所有 POST/PUT/DELETE 必须携带 X-Write-Token 头，防止同网段设备随意触发抓取/改配置/删收藏。
# 口令来源：运行时 secret 文件、环境变量，或本地开发 token 文件（见 config.get_write_token）。
WRITE_TOKEN = get_write_token()
print('[API] 写操作口令已启用（写接口需 X-Write-Token 请求头）')


def _current_identity():
    """身份判定链（三态，每请求缓存一次）：
    1. X-Write-Token 命中 → 超级管理员（应急后门，永不过期）
    2. HttpOnly 会话 Cookie → 会话有效且 mid ∈ PostgreSQL 管理员名单 → 管理员
    3. 其余 → 访客（含"已登录B站但不在名单"的有身份访客）
    """
    ident = getattr(g, 'kb_identity', None)
    if ident is not None:
        return ident
    vid = request.headers.get('X-Visitor-Id', '').strip()
    vid = vid if vid and 0 < len(vid) <= 64 else None
    # B站会话用户信息先统一解析（写口令与会话同时携带时，写口令只决定 admin 权限，
    # 不吞掉 user，否则站长扫码登录后 /auth/me 仍返回 user=null → 前端误判未登录）。
    token = request.cookies.get(SESSION_COOKIE_NAME, '').strip()
    sess = get_session(token) if token else None
    user = None
    if sess:
        user = {'mid': sess.get('mid'), 'name': sess.get('name'), 'face': sess.get('face')}
    if request.headers.get('X-Write-Token', '') == WRITE_TOKEN:
        # 应急后门：写口令命中即超管，但仍透传 B站会话 user
        ident = {'admin': True, 'via': 'write_token', 'user': user, 'visitor_id': vid}
    elif sess:
        ident = {'admin': is_admin_mid(sess.get('mid')), 'via': 'session',
                 'user': user, 'visitor_id': vid}
    else:
        ident = {'admin': False, 'via': None, 'user': None, 'visitor_id': vid}
    g.kb_identity = ident
    return ident


def _is_admin():
    """管理员判定：写口令（超管后门）或 B站管理员账号会话"""
    return _current_identity()['admin']


def _fav_owner():
    """收藏归属（2026-08-29 起）：登录 B站账号 → str(mid)（跨设备持久）；未登录 → None。

    写口令是超管应急后门，不参与收藏归属——站长也需扫码登录一次绑定账号。
    即使写口令与会话 Cookie 同时携带，也优先取会话 mid（避免写口令短路导致拿不到账号）。
    返回 (owner, ident)：ident 用于判断是否 B站管理员会话（迁移存量收藏用）。
    """
    ident = _current_identity()
    user = ident.get('user') or {}
    if user.get('mid'):
        return str(user['mid']), ident
    return None, ident


def _require_admin():
    """路由级管理员守卫：非管理员返回 403 响应，管理员返回 None 放行"""
    if not _is_admin():
        return jsonify({'success': False, 'message': '需要管理员权限'}), 403
    return None


def _request_actor():
    """生成任务审计用的操作者标签，不包含任何凭证。"""
    ident = _current_identity()
    user = ident.get('user') or {}
    if user.get('mid'):
        return f"{ident.get('via') or 'session'}:{user['mid']}"
    return ident.get('via') or 'system'


# ==================== /auth/verify 失败限速 ====================
# 防口令试错（防御纵深：口令本身 128bit 随机不可爆破，此处只挡高频试错/脚本扫描）。
# 每客户端 IP 15 分钟滑动窗口内 5 次失败 → 锁定期内错误口令直接 429（不再比对）；
# 正确口令始终放行——恶意访客只能锁死自己的 IP，无法影响管理员登录。
# 纯内存实现，重启即清零；threaded=True 下用锁保护。

_VERIFY_FAILURES = {}      # ip -> [失败时间戳]
_VERIFY_FAIL_LIMIT = 5     # 窗口内允许的失败次数
_VERIFY_WINDOW = 15 * 60   # 滑动窗口（秒）
_verify_lock = threading.Lock()


def _client_ip():
    """客户端 IP：ProxyFix 开启时 remote_addr 已由唯一可信代理层规范化。"""
    return request.remote_addr or 'unknown'


def _is_verify_locked(ip):
    with _verify_lock:
        cutoff = time.time() - _VERIFY_WINDOW
        fails = [t for t in _VERIFY_FAILURES.get(ip, []) if t > cutoff]
        _VERIFY_FAILURES[ip] = fails
        if not fails:
            _VERIFY_FAILURES.pop(ip, None)
        return len(fails) >= _VERIFY_FAIL_LIMIT


def _record_verify_failure(ip):
    with _verify_lock:
        _VERIFY_FAILURES.setdefault(ip, []).append(time.time())


def _clear_verify_failures(ip):
    with _verify_lock:
        _VERIFY_FAILURES.pop(ip, None)


@app.before_request
def _require_write_token():
    # 收藏接口豁免全局写口令：访客凭 X-Visitor-Id 即可收藏自己的内容（路由内自行校验归属）
    if request.path.startswith('/api/favorites'):
        return None
    # UP追踪申请接口豁免全局写口令：访客凭 X-Visitor-Id 提交/撤回自己的申请。
    # 审核操作（review）在路由内要求管理员（写口令或B站管理员会话），列表（GET）路由内 403。
    if request.method == 'POST' and request.path.startswith('/api/up-trends/requests'):
        return None
    # B站会话登出豁免全局写口令：已登录访客凭 HttpOnly Cookie 退出自己的登录（路由内校验）
    if request.method == 'POST' and request.path == '/api/bili-auth/logout':
        return None
    if request.method in ('POST', 'PUT', 'DELETE'):
        if not _is_admin():
            # 仅 /api/auth/verify 的失败计入限速（这是唯一可试口令的入口）
            if request.path == '/api/auth/verify':
                ip = _client_ip()
                if _is_verify_locked(ip):
                    return jsonify({'success': False, 'message': '尝试次数过多，请15分钟后再试'}), 429
                _record_verify_failure(ip)
            return jsonify({'success': False, 'message': '需要管理员权限（写口令或B站管理员登录）'}), 401

# ==================== Dashboard API ====================

# 响应级缓存：数据一天只变几次，而前端每 15 秒轮询一次。
# get_data() 已有内存缓存（避免读盘），但每次请求仍会重跑 filter_danmaku_words
# 和组装整个响应 dict。这里把组装结果按 (数据版本, 实时缓存时刻) 缓存，
# 数据未变时直接复用，过滤与组装零开销。
_dash_payload_cache = {'key': None, 'payload': None}
_dash_payload_lock = threading.RLock()


def _invalidate_dashboard_payload():
    """配置变更后清除响应缓存，避免规则已保存但页面仍展示旧过滤结果。"""
    with _dash_payload_lock:
        _dash_payload_cache['key'] = None
        _dash_payload_cache['payload'] = None


def _with_radar_metrics(videos):
    """为 API 响应复制视频行并附加雷达数据，不污染缓存中的原始采集结果。"""
    from utils.radar_metrics import build_radar_metrics
    return [
        {**video, 'radar': build_radar_metrics(video)} if isinstance(video, dict) else video
        for video in (videos or [])
    ]


def _with_video_observations(videos):
    from services.radar_service import RadarService
    from storage.repositories.radar import get_radar_repository
    return RadarService(get_radar_repository()).decorate(videos or [], int(time.time()))


def _build_dashboard_payload(data, is_live, live_cached_at=None, now=None):
    """组装 /api/dashboard 响应体（弹幕热词过滤在数据变化时只执行一次）"""
    from services.radar_service import RadarService
    from storage.repositories.radar import get_radar_repository
    now = int(time.time()) if now is None else now
    fields = ('kichu_rank', 'hot_videos', 'material_candidates')
    all_rows = [v for field in fields for v in (data.get(field) or [])]
    decorated = RadarService(get_radar_repository()).decorate(all_rows, now)
    # Keep each section's own scores/metadata, even when a bvid occurs in several lists.
    sections = {}
    offset = 0
    for field in fields:
        count = len(data.get(field) or [])
        sections[field] = decorated[offset:offset+count]
        offset += count
    def rows(field, v2=False):
        source = sections[field]
        return source if v2 else _with_radar_metrics(source)
    return {
        'kichu_rank': rows('kichu_rank', True),
        'hot_memes': data.get('hot_memes', []),
        'hot_songs': data.get('hot_songs', []),
        'hot_videos': rows('hot_videos', True),
        'material_candidates': rows('material_candidates'),
        'meme_materials': data.get('meme_materials', []),
        'danmaku_words': filter_danmaku_words(data.get('danmaku_words', [])),
        'comments_gold': data.get('comments_gold', []),
        'last_updated': data.get('last_updated'),
        'is_live': is_live,
        'live_cached_at': live_cached_at,
    }


@app.route('/internal/public-pages', methods=['GET'])
def route_public_pages():
    from services.public_pages import load_public_pages
    try:
        return jsonify(load_public_pages())
    except Exception:
        app.logger.error('Public page export unavailable')
        return jsonify({'success': False}), 503


@app.route('/api/dashboard', methods=['GET'])
def route_dashboard():
    """看板数据：优先返回实时缓存（手动抓取，未过期），否则返回定时数据（数据库）。

    - 实时缓存未过期：返回实时数据 + is_live=True 标识
    - 实时缓存过期/不存在：返回定时数据 + is_live=False 标识
    """
    from storage.cache import get_live_cache, get_data_version

    # 优先读实时缓存（手动抓取数据，未过期则返回）
    live = get_live_cache()
    if live:
        data = live['data']
        is_live = True
        live_cached_at = live['cached_at']
        cache_key = ('live', live_cached_at)
    else:
        data = get_data()
        is_live = False
        live_cached_at = None
        # 定时数据：以数据版本号为缓存键（数据未变则复用组装结果）
        cache_key = ('timer', get_data_version())

    from storage.repositories.radar import get_radar_repository
    repository = get_radar_repository()
    now = int(time.time())
    cache_key += (repository.revision() if repository else (0, None)) + (now//60,)
    with _dash_payload_lock:
        if _dash_payload_cache['key'] != cache_key:
            payload = _build_dashboard_payload(data, is_live, live_cached_at, now)
            _dash_payload_cache.update(key=cache_key, payload=payload)
        return jsonify({'success': True, 'data': _dash_payload_cache['payload']})


@app.route('/api/memes', methods=['GET'])
def route_memes():
    data = get_data()
    return jsonify({'success': True, 'data': data.get('hot_memes', [])})


@app.route('/api/songs', methods=['GET'])
def route_songs():
    data = get_data()
    return jsonify({'success': True, 'data': data.get('hot_songs', [])})


@app.route('/api/videos', methods=['GET'])
def route_videos():
    data = get_data()
    return jsonify({'success': True, 'data': _with_video_observations(data.get('hot_videos'))})


@app.route('/api/kichu-rank', methods=['GET'])
def route_kichu_rank():
    data = get_data()
    return jsonify({'success': True, 'data': _with_video_observations(data.get('kichu_rank'))})


@app.route('/api/meme-materials', methods=['GET'])
def route_meme_materials():
    data = get_data()
    return jsonify({'success': True, 'data': data.get('meme_materials', [])})


@app.route('/api/material-candidates', methods=['GET'])
def route_material_candidates():
    data = get_data()
    return jsonify({'success': True, 'data': _with_radar_metrics(
        _with_video_observations(data.get('material_candidates')))})


@app.route('/api/danmaku', methods=['GET'])
def route_danmaku():
    data = get_data()
    return jsonify({
        'success': True,
        'data': filter_danmaku_words(data.get('danmaku_words', [])),
    })


@app.route('/api/comments', methods=['GET'])
def route_comments():
    data = get_data()
    return jsonify({'success': True, 'data': data.get('comments_gold', [])})


@app.route('/api/proxy/image')
def route_proxy_image():
    img_url = request.args.get('url', '')
    if not img_url:
        return 'No url', 400
    allowed_hosts = ['hdslb.com', 'bilibili.com', 'biliimg.com']
    if not any(h in img_url for h in allowed_hosts):
        return 'Invalid url', 403
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://www.bilibili.com/',
        }
        resp = requests.get(img_url, headers=headers, timeout=10, stream=True)
        content_type = resp.headers.get('Content-Type', 'image/jpeg')
        return Response(
            resp.iter_content(chunk_size=8192),
            content_type=content_type,
            headers={
                'Cache-Control': 'public, max-age=86400',
                'Access-Control-Allow-Origin': '*',
            }
        )
    except Exception as e:
        return f'Error: {e}', 500


# ==================== Favorites API ====================

@app.route('/api/favorites', methods=['GET'])
def route_list_favorites():
    """读收藏：按 B站账号(mid)过滤；B站管理员会话首次访问自动迁移存量收藏"""
    owner, ident = _fav_owner()
    if owner is None:
        return jsonify({'success': False, 'message': '请先登录 B站账号'}), 401
    if ident.get('admin') and ident.get('via') == 'session':
        migrate_legacy_favorites(owner)
    item_type = request.args.get('type')
    tag = request.args.get('tag')
    favs = get_favorites(item_type=item_type, tag=tag, owner=owner)
    return jsonify({'success': True, 'data': favs})


@app.route('/api/favorites', methods=['POST'])
def route_create_favorite():
    owner, _ = _fav_owner()
    if owner is None:
        return jsonify({'success': False, 'message': '请先登录 B站账号'}), 401
    body = request.get_json()
    item_type = body.get('type', 'meme')
    item = body.get('item', {})
    result = add_favorite(item_type, item, owner=owner)
    return jsonify({'success': True, 'data': result})


@app.route('/api/favorites/<item_id>', methods=['DELETE'])
def route_delete_favorite(item_id):
    owner, _ = _fav_owner()
    if owner is None:
        return jsonify({'success': False, 'message': '请先登录 B站账号'}), 401
    if not remove_favorite(item_id, owner=owner):
        return jsonify({'success': False, 'message': '未找到该收藏'}), 404
    return jsonify({'success': True, 'message': '删除成功'})


@app.route('/api/favorites/<item_id>', methods=['PUT'])
def route_modify_favorite(item_id):
    owner, _ = _fav_owner()
    if owner is None:
        return jsonify({'success': False, 'message': '请先登录 B站账号'}), 401
    body = request.get_json()
    result = update_favorite(
        item_id,
        tags=body.get('tags'),
        notes=body.get('notes'),
        owner=owner,
    )
    if result:
        return jsonify({'success': True, 'data': result})
    return jsonify({'success': False, 'message': '未找到该收藏'}), 404


# ==================== Crawl Status API ====================

@app.route('/api/refresh', methods=['POST'])
def route_refresh():
    """手动刷新：实时抓取，数据不落库，只更新实时缓存。

    与定时抓取共用 _crawl_lock 互斥，不会并发。
    数据仅供即时展示，TTL 10 分钟后自动回退到定时数据（数据库）。
    """
    if not try_acquire_lock():
        return jsonify({
            'success': False,
            'message': '数据正在更新中，请稍候',
            'crawling': True,
        }), 409
    mark_crawling()

    def _safe_crawl_live():
        """实时抓取线程入口：吞掉 _crawl_job_live 抛出的异常。

        实时抓取失败时清空实时缓存，前端会自动回退到定时数据。
        """
        try:
            _crawl_job_live('manual')
        except Exception:
            pass  # 异常已记录在 _crawl_status，前端轮询 /api/status 可见

    thread = threading.Thread(target=_safe_crawl_live, daemon=True)
    thread.start()
    return jsonify({
        'success': True,
        'message': '已开始实时刷新（约2-3分钟），数据不落库',
        'crawling': True,
    })


@app.route('/api/status', methods=['GET'])
def route_status():
    """抓取状态查询：前端状态条轮询用"""
    data = get_data()
    status = get_status()
    # 登录态检测：未登录时 412 限流风险升高，前端提示用户重新扫码
    try:
        from collectors.bilibili_auth import is_logged_in
        bili_logged_in = is_logged_in()
    except Exception:
        bili_logged_in = False  # 模块加载失败视为未登录
    # 数据来源：实时缓存存在且未过期 = live，否则 = scheduled
    from storage.cache import get_live_cache
    data_source = 'live' if get_live_cache() else 'scheduled'
    from storage.repositories.radar import get_radar_repository
    repository = get_radar_repository()
    observation_revision = repository.revision() if repository else (0, None)
    # 同接熔断器状态（L3）：fails/是否打开/冷却倒计时/半开态/状态趋势，便于运维排查风控
    try:
        from collectors.bilibili import (_ONLINE_BREAKER, _online_breaker_open,
                                         get_online_breaker_trend)
        ob = dict(_ONLINE_BREAKER)
        ob['open'] = _online_breaker_open()
        ob['half_open'] = ob['fails'] >= ONLINE_BREAK_THRESHOLD and not ob['open']
        ob['cooldown_remaining'] = (
            max(0, int(ob['open_ts'] + ONLINE_BREAK_COOLDOWN - time.time()))
            if ob['fails'] >= ONLINE_BREAK_THRESHOLD and ob['open'] else 0
        )
        ob['threshold'] = ONLINE_BREAK_THRESHOLD  # 熔断阈值（前端趋势图阈值线用，配置化不硬编码）
        ob['trend'] = get_online_breaker_trend(50)  # 熔断状态历史（趋势图数据源）
    except Exception:
        ob = None
    return jsonify({
        'success': True,
        'data': {
            'crawling': status['crawling'],
            'started_at': status['started_at'],
            'last_finished_at': status['last_finished_at'],
            'last_error': status['last_error'],
            'last_updated': data.get('last_updated'),
            'bili_logged_in': bili_logged_in,      # B站登录态（过期时前端提示重新扫码）
            'data_source': data_source,             # 数据来源：live(实时)/scheduled(定时)
            'observation_revision': observation_revision,
            'online_breaker': ob,                   # 同接熔断器状态（null=不可用）
        }
    })


@app.route('/api/health/live', methods=['GET'])
def route_health_live():
    """Process liveness only; deliberately does not access persistence."""
    return jsonify({'success': True, 'status': 'live'})


@app.route('/api/health/ready', methods=['GET'])
def route_health_ready():
    """Readiness checks are supplied by the configured PostgreSQL runtime."""
    service = app.config.get('READINESS_SERVICE')
    ready, reason = service.check() if service is not None else (False, 'readiness_not_configured')
    payload = {'success': ready, 'status': 'ready' if ready else 'not_ready'}
    if reason:
        payload['reason'] = reason
    return jsonify(payload), 200 if ready else 503


@app.route('/api/health', methods=['GET'])
def route_health():
    """Legacy health endpoint is intentionally a readiness alias."""
    return route_health_ready()


# ==================== Auth / 管理员 API ====================

@app.route('/api/auth/verify', methods=['POST'])
def route_auth_verify():
    """管理员口令验证（前端超管登录入口 / 应急后门）。

    能进入本路由说明 before_request 已校验通过（写口令或B站管理员会话）；
    凭证缺失/错误在 before_request 就地返回 401（失败计入限速，见 _require_write_token）。
    """
    _clear_verify_failures(_client_ip())  # 登录成功即清零失败计数
    return jsonify({'success': True, 'data': {'admin': True}})


@app.route('/api/auth/me', methods=['GET'])
def route_auth_me():
    """当前身份查询（前端启动/登录后刷新用）。

    data.admin → 是否管理员；data.via → 凭证来源（write_token/session/null）；
    data.user → B站身份（未登录为 null；超管口令登录无B站身份亦为 null）。
    """
    ident = _current_identity()
    return jsonify({'success': True, 'data': {
        'admin': ident['admin'],
        'via': ident['via'],
        'user': ident['user'],
    }})


# ==================== 管理员名单 API（B站账号判定） ====================
# 名单存 PostgreSQL auth.admin_accounts；增删均要求管理员（超管口令或B站管理员会话）。

@app.route('/api/admin/accounts', methods=['GET'])
def route_admin_accounts_list():
    guard = _require_admin()
    if guard:
        return guard
    accounts = list_admin_accounts()
    admin_mids = {a['mid'] for a in accounts}
    recent = list_recent_logins(10)
    for r in recent:
        r['is_admin'] = r.get('mid') in admin_mids
    return jsonify({'success': True, 'data': {
        'accounts': accounts,
        'recent_logins': recent,
    }})


@app.route('/api/admin/accounts', methods=['POST'])
def route_admin_accounts_add():
    guard = _require_admin()
    if guard:
        return guard
    body = request.get_json(silent=True) or {}
    mid = body.get('mid')
    if isinstance(mid, bool):
        return jsonify({'success': False, 'message': 'mid 参数错误'}), 400
    if isinstance(mid, str):
        mid = mid.strip()
        if not mid.isdigit():
            return jsonify({'success': False, 'message': 'mid 参数错误'}), 400
        mid = int(mid)
    if not isinstance(mid, int) or mid <= 0:
        return jsonify({'success': False, 'message': 'mid 参数错误'}), 400

    name = str(body.get('name') or '').strip()[:50]
    face = str(body.get('face') or '').strip()[:500]
    ident = _current_identity()
    if ident['via'] == 'write_token':
        added_by = 'write-token'
    elif ident['user']:
        added_by = f"mid:{ident['user'].get('mid')}"
    else:
        added_by = 'unknown'

    row, err = add_admin_account(mid, name, face, added_by)
    if err == 'EXISTS':
        return jsonify({'success': False, 'message': '该B站账号已在管理员名单'}), 409
    if err:
        return jsonify({'success': False, 'message': 'mid 参数错误'}), 400
    return jsonify({'success': True, 'data': row})


@app.route('/api/admin/accounts/<int:mid>', methods=['DELETE'])
def route_admin_accounts_remove(mid):
    guard = _require_admin()
    if guard:
        return guard
    ok, err = remove_admin_account(mid)
    if err == 'LAST_ADMIN':
        return jsonify({'success': False, 'message': '至少保留一名管理员，防止自锁'}), 400
    if err == 'NOT_FOUND':
        return jsonify({'success': False, 'message': '该账号不在管理员名单'}), 404
    return jsonify({'success': True, 'data': {'mid': mid}})


# ==================== B站 Auth API（多会话登录，身份与采集解耦） ====================
# 身份登录（全员开放）：访客扫码登录自己的B站账号，凭证只落服务器会话表
#   （PostgreSQL auth.bili_sessions），浏览器仅持 session token；不写采集 Cookie。
# 采集登录（管理员专属）：扫码凭证写入 bilibili_cookie.json（爬虫专用），
#   防止访客顶替服务器爬虫 Cookie。

_QR_PENDING = {}   # qrcode_key -> {'visitor_id', 'purpose', 'created_at'}
_QR_TTL = 300      # 二维码待完成登录的有效期（秒）
_qr_lock = threading.Lock()


def _qr_register(key, visitor_id, purpose):
    with _qr_lock:
        now = time.time()
        for k in list(_QR_PENDING):
            if _QR_PENDING[k]['created_at'] < now - _QR_TTL:
                _QR_PENDING.pop(k, None)
        _QR_PENDING[key] = {'visitor_id': visitor_id, 'purpose': purpose, 'created_at': now}


def _qr_lookup(key):
    with _qr_lock:
        return _QR_PENDING.get(key)


@app.route('/api/bili-auth/qrcode', methods=['GET'])
def route_bili_qrcode():
    """身份登录二维码（全员开放）：登录的是访客自己的B站账号。

    key 与发起访客绑定（check 时校验），防止二维码 key 被挪用。
    """
    vid = _visitor_id_header()
    if not vid:
        return jsonify({'success': False, 'message': '缺少访客身份'}), 401
    result = generate_qrcode()
    if result.get('success') and result.get('qrcode_key'):
        _qr_register(result['qrcode_key'], vid, 'identity')
    return jsonify(result)


@app.route('/api/bili-auth/check', methods=['GET'])
def route_bili_check_login():
    """身份登录完成：轮询扫码结果，成功则签发会话 token。

    安全：SESSDATA/bili_jct 只落服务器会话表，绝不回传浏览器；
    身份登录不写采集 Cookie（save=False）。
    """
    key = request.args.get('key', '')
    if not key:
        return jsonify({'success': False, 'message': '缺少key参数'}), 400
    pending = _qr_lookup(key)
    if not pending or pending.get('purpose') != 'identity':
        return jsonify({'success': False, 'message': '登录二维码不存在或已过期，请刷新'}), 404
    vid = _visitor_id_header()
    if vid != pending['visitor_id']:
        return jsonify({'success': False, 'message': '登录身份不匹配'}), 403

    result = check_login_status(key, save=False)
    if not isinstance(result, dict):
        return jsonify({'success': False, 'message': '登录检查失败'}), 502
    if not (result.get('success') and result.get('status') == 'success'):
        return jsonify(result)  # waiting / scanned / expired 等中间态原样透传

    cookies = result.pop('cookies', None) or {}
    # 昵称头像补充（nav 接口尽力而为，失败不阻断登录）
    info = {}
    try:
        info = get_user_info_with_cookie(cookie_dict_to_str(cookies)) or {}
    except Exception:
        info = {}
    mid = result.get('user_mid') or cookies.get('DedeUserID') or info.get('mid')
    try:
        mid = int(mid)
    except (TypeError, ValueError):
        mid = 0
    name = info.get('name') or (f'UID {mid}' if mid else '未知用户')
    face = info.get('face') or ''

    token = create_session(pending['visitor_id'], mid, name, face, cookies)
    update_admin_profile(mid, name, face)  # 管理员名单资料自愈（不在名单时 no-op）
    with _qr_lock:
        _QR_PENDING.pop(key, None)
    response = jsonify({
        'success': True, 'status': 'success', 'message': '登录成功',
        'user': {'mid': mid, 'name': name, 'face': face},
        'is_admin': is_admin_mid(mid),
    })
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        httponly=True,
        secure=True,
        samesite='Lax',
        path='/',
    )
    return response


@app.route('/api/bili-auth/logout', methods=['POST'])
def route_bili_logout():
    """退出B站身份登录（销毁当前浏览器会话；不影响采集 Cookie）。

    豁免全局写口令：已登录访客凭 HttpOnly Cookie 即可退出自己的登录。
    """
    token = request.cookies.get(SESSION_COOKIE_NAME, '').strip()
    if not token:
        return jsonify({'success': False, 'message': '未登录'}), 401
    delete_session(token)
    response = jsonify({'success': True, 'message': '已退出登录'})
    response.delete_cookie(
        SESSION_COOKIE_NAME,
        path='/',
        secure=True,
        httponly=True,
        samesite='Lax',
    )
    return response


@app.route('/api/bili-auth/user', methods=['GET'])
def route_bili_user_info():
    """采集账号信息（管理员专属）：bilibili_cookie.json 对应账号的昵称头像"""
    guard = _require_admin()
    if guard:
        return guard
    user = get_user_info()
    if user:
        return jsonify({'success': True, 'data': user})
    return jsonify({'success': False, 'message': '未登录或Cookie已过期'})


@app.route('/api/bili-auth/collect-login', methods=['GET'])
def route_bili_collect_login():
    """采集账号登录二维码（管理员专属）：扫码凭证将写入爬虫 Cookie"""
    guard = _require_admin()
    if guard:
        return guard
    result = generate_qrcode()
    if result.get('success') and result.get('qrcode_key'):
        _qr_register(result['qrcode_key'], _visitor_id_header() or 'admin', 'collect')
    return jsonify(result)


@app.route('/api/bili-auth/collect-check', methods=['GET'])
def route_bili_collect_check():
    """采集账号登录完成（管理员专属）：持久交接给 Worker 写入 Cookie。

    安全：凭证只落服务器磁盘，绝不回传浏览器。
    """
    guard = _require_admin()
    if guard:
        return guard
    key = request.args.get('key', '')
    if not key:
        return jsonify({'success': False, 'message': '缺少key参数'}), 400
    pending = _qr_lookup(key)
    if not pending or pending.get('purpose') != 'collect':
        return jsonify({'success': False, 'message': '登录二维码不存在或已过期，请刷新'}), 404
    result = check_login_status(key, save=False)
    if isinstance(result, dict):
        cookies = result.pop('cookies', None) or {}
        if result.get('success'):
            request_collector_cookie_update(cookies, _current_identity()['via'])
            with _qr_lock:
                _QR_PENDING.pop(key, None)
    return jsonify(result)


@app.route('/api/bili-auth/collect-logout', methods=['POST'])
def route_bili_collect_logout():
    """采集账号退出（管理员专属）：请求 Worker 清除爬虫 Cookie 文件"""
    guard = _require_admin()
    if guard:
        return guard
    request_collector_logout(_current_identity()['via'])
    return jsonify({'success': True, 'message': '采集账号已退出'})


# ==================== UP主动态 API ====================

@app.route('/api/up-trends/config', methods=['GET'])
def route_up_trends_config():
    return jsonify({'success': True, 'data': load_config()})


@app.route('/api/up-trends/config', methods=['POST'])
def route_up_trends_config_update():
    config = request.get_json() or {}
    save_config(config)
    return jsonify({'success': True, 'data': load_config()})


# ==================== UP追踪申请 API（访客提交 / 站长审核）====================
# 方案C（公网多用户）：访客凭 X-Visitor-Id 申请添加追踪UP，站长审核入池。
# 与收藏接口同款豁免模式：before_request 放行 POST，路由内自行鉴权。

# 搜索代理防风控：关键词结果缓存 5 分钟 + 每访客 10 次/分钟滑动窗口
_UP_SEARCH_CACHE = {}        # keyword -> (过期时间戳, data)
_UP_SEARCH_CACHE_TTL = 5 * 60
_UP_SEARCH_RATE = {}         # visitor_id -> [请求时间戳]
_UP_SEARCH_RATE_LIMIT = 10
_UP_SEARCH_RATE_WINDOW = 60
_up_search_lock = threading.Lock()

_REQUEST_ERROR_MAP = {
    'ALREADY_TRACKED': (409, '该UP主已在追踪名单中'),
    'POOL_FULL': (409, '追踪池已满（软上限300）'),
    'DUPLICATE': (409, '该UP主已有待审核申请'),
    'QUEUE_FULL': (429, '待审核队列已满，请稍后再试'),
    'DAILY_LIMIT': (429, '今日申请次数已达上限（每日3次）'),
}


def _visitor_id_header():
    """取合法访客ID：1-64字符非空串，否则 None"""
    vid = request.headers.get('X-Visitor-Id', '').strip()
    return vid if vid and len(vid) <= 64 else None


@app.route('/api/up-trends/search', methods=['GET'])
def route_up_trends_search():
    """UP主昵称搜索代理（访客申请弹窗用）。

    限速 + 缓存都在后端做：前端不直连B站（防风控/防跨域）。
    搜索失败返回 503，前端降级提示"粘贴UP主页链接"。
    """
    vid = _visitor_id_header()
    if not vid:
        return jsonify({'success': False, 'message': '缺少访客身份'}), 401
    keyword = (request.args.get('keyword') or '').strip()
    if not keyword:
        return jsonify({'success': False, 'message': '缺少 keyword 参数'}), 400

    now = time.time()
    cached_data = None
    with _up_search_lock:
        # 限速：滑动窗口内超过 10 次 → 429（缓存命中也计数，防脚本刷接口）
        calls = [t for t in _UP_SEARCH_RATE.get(vid, []) if t > now - _UP_SEARCH_RATE_WINDOW]
        if len(calls) >= _UP_SEARCH_RATE_LIMIT:
            _UP_SEARCH_RATE[vid] = calls
            return jsonify({'success': False, 'message': '搜索过于频繁，请稍后再试'}), 429
        calls.append(now)
        _UP_SEARCH_RATE[vid] = calls
        # 缓存命中：免打B站
        cached = _UP_SEARCH_CACHE.get(keyword)
        if cached and cached[0] > now:
            cached_data = cached[1]

    if cached_data is not None:
        return jsonify({'success': True, 'data': cached_data})

    users = search_up_users(keyword)
    if users is None:
        return jsonify({
            'success': False,
            'message': '搜索暂不可用（可能被限流），请粘贴UP主页链接申请',
        }), 503
    with _up_search_lock:
        _UP_SEARCH_CACHE[keyword] = (time.time() + _UP_SEARCH_CACHE_TTL, users)
    return jsonify({'success': True, 'data': users})


@app.route('/api/up-trends/requests', methods=['POST'])
def route_up_trends_request_submit():
    """访客提交追踪申请（body: {mid, reason?}，reason 选填）。

    提交时拉取 UP 快照（name/face/sign/fans）存入申请单，
    站长审核页直接展示，无需再开B站请求。
    """
    vid = _visitor_id_header()
    if not vid:
        return jsonify({'success': False, 'message': '缺少访客身份'}), 401

    body = request.get_json(silent=True) or {}
    mid = body.get('mid')
    if isinstance(mid, bool):
        return jsonify({'success': False, 'message': 'mid 参数错误'}), 400
    if isinstance(mid, str):
        mid = mid.strip()
        if not mid.isdigit():
            return jsonify({'success': False, 'message': 'mid 参数错误'}), 400
        mid = int(mid)
    if not isinstance(mid, int) or mid <= 0:
        return jsonify({'success': False, 'message': 'mid 参数错误'}), 400

    reason = str(body.get('reason') or '').strip()[:200]
    request_type = body.get('request_type', 'add')
    if request_type not in ('add', 'remove'):
        return jsonify({'success': False, 'message': '申请类型错误'}), 400
    if request_type == 'remove':
        snapshot = next((u for u in (load_tracked_list() or {}).get('ups', [])
                         if u.get('mid') == mid and u.get('enabled', True)), None)
        if not snapshot:
            return jsonify({'success': False, 'message': '该UP主当前未被观测'}), 409
        if not reason:
            return jsonify({'success': False, 'message': '请填写停止观测的原因'}), 400
        req, err = add_up_request(mid, snapshot, reason, vid, request_type='remove')
        if err:
            status, msg = _REQUEST_ERROR_MAP.get(err, (409, '名单状态已变化，请刷新后重试'))
            return jsonify({'success': False, 'code': err, 'message': msg}), status
        return jsonify({'success': True, 'data': req})

    info = get_up_info_by_mid(mid)
    if not info:
        return jsonify({'success': False, 'message': '获取UP主信息失败（mid不存在或接口异常）'}), 502
    rel = get_up_relation_stat(mid) or {}
    snapshot = {
        'mid': mid,
        'name': info.get('name', ''),
        'face': info.get('face', ''),
        'sign': info.get('sign', ''),
        'fans': rel.get('follower', 0),
    }

    req, err = add_up_request(mid, snapshot, reason, vid)
    if err:
        status, msg = _REQUEST_ERROR_MAP.get(err, (400, err))
        return jsonify({'success': False, 'code': err, 'message': msg}), status
    return jsonify({'success': True, 'data': req})


@app.route('/api/up-trends/requests/mine', methods=['GET'])
def route_up_trends_requests_mine():
    """访客查自己的申请（pending + processed，拒绝理由可见）"""
    vid = _visitor_id_header()
    if not vid:
        return jsonify({'success': False, 'message': '缺少访客身份'}), 401
    return jsonify({'success': True, 'data': get_my_up_requests(vid)})


@app.route('/api/up-trends/roster', methods=['GET'])
def route_up_trends_roster():
    """公开实际启用名单；不暴露配置、申请或采集账号信息。"""
    tracked = load_tracked_list() or {}
    ups = [{key: up.get(key) for key in ('mid', 'name', 'face', 'added_at')}
           for up in tracked.get('ups', []) if up.get('enabled', True)]
    return jsonify({'success': True, 'data': {'ups': ups, 'total': len(ups),
                                             'updated_at': tracked.get('updated_at', 0)}})


@app.route('/api/up-trends/roster/manage', methods=['GET'])
def route_up_trends_roster_manage():
    guard = _require_admin()
    if guard:
        return guard
    tracked = load_tracked_list() or {}
    ups = tracked.get('ups', [])
    return jsonify({'success': True, 'data': {
        'unchanged': ups, 'added': [], 'removed': [],
        'existing_count': len(ups), 'total_fresh': len(ups),
    }})


@app.route('/api/up-trends/requests/<req_id>/withdraw', methods=['POST'])
def route_up_trends_request_withdraw(req_id):
    """访客撤回自己的待审核申请（已处理/已撤回 → 404）"""
    vid = _visitor_id_header()
    if not vid:
        return jsonify({'success': False, 'message': '缺少访客身份'}), 401
    err = withdraw_up_request(req_id, vid)
    if err == 'NOT_OWNER':
        return jsonify({'success': False, 'message': '只能撤回自己的申请'}), 403
    if err == 'NOT_FOUND':
        return jsonify({'success': False, 'message': '申请不存在或已处理'}), 404
    return jsonify({'success': True, 'message': '已撤回'})


@app.route('/api/up-trends/requests', methods=['GET'])
def route_up_trends_requests_admin():
    """站长审核列表：全部待审核 + 最近已处理（需管理员）"""
    guard = _require_admin()
    if guard:
        return guard
    return jsonify({'success': True, 'data': list_all_up_requests()})


def _land_approved_up(req):
    """审核通过后的即时落地（不等下一个分析批次，前端立即可见）：

    1. up_obs 并入最新批次（ts=最新批次时刻，不新开批次；无批次则当前时刻开新）
    2. ups 表登记（mid/name/face）
    3. 将该 UP 的日历基线回填加入持久化队列
    """
    mid = req['mid']
    up = req.get('up') or {}
    ts = get_latest_batch_ts() or int(time.time())
    try:
        upsert_up_obs(
            ts=ts,
            up_list=[{
                'mid': mid,
                'follower_count': up.get('fans', 0),
                'sign': up.get('sign', ''),
            }],
        )
    except Exception as e:
        print(f'up_obs 即时落地失败 {mid}: {e}')
    try:
        register_up(mid, name=up.get('name', ''), face=up.get('face', ''))
    except Exception as e:
        print(f'ups 表登记失败 {mid}: {e}')

    try:
        from jobs.calendar_jobs import enqueue_baseline_jobs
        enqueue_baseline_jobs(
            [mid], requested_by=_request_actor(), reason='追踪申请审核通过',
        )
    except Exception as e:
        print(f'日历基线任务创建失败 {mid}: {e}')


@app.route('/api/up-trends/requests/<req_id>/review', methods=['POST'])
def route_up_trends_request_review(req_id):
    """站长审核（body: {action: 'approve'|'reject', reason?}）。

    - approve：入池 + 即时落地（up_obs/ups/日历回填）；已在池则幂等通过
    - reject：必须填理由（访客可见）
    - 鉴权失败返回 401（写操作语义），区别于审核列表 GET 的 403
    """
    if not _is_admin():
        return jsonify({'success': False, 'message': '需要管理员权限'}), 401

    body = request.get_json(silent=True) or {}
    action = body.get('action')
    if action not in ('approve', 'reject'):
        return jsonify({'success': False, 'message': 'action 必须为 approve 或 reject'}), 400
    reject_reason = str(body.get('reason') or '').strip()
    if action == 'reject' and not reject_reason:
        return jsonify({'success': False, 'message': '拒绝时必须填写理由（访客可见）'}), 400

    result, err = review_up_request(req_id, action, reject_reason=reject_reason or None)
    if err == 'POOL_FULL':
        return jsonify({'success': False, 'message': '观测名单已满，请先停止部分观测'}), 409
    if err == 'NOT_FOUND':
        # 区分"已处理"（并发双击/重复审核 → 409）与"不存在"（404）
        processed_ids = {r.get('id') for r in list_all_up_requests()['processed']}
        if req_id in processed_ids:
            return jsonify({'success': False, 'message': '该申请已处理'}), 409
        return jsonify({'success': False, 'message': '申请不存在'}), 404

    if action == 'approve' and result.get('added_to_pool'):
        _land_approved_up(result['request'])
    return jsonify({'success': True, 'data': result})


# ==================== 开发者模式配置 API ====================

@app.route('/api/config/meme-stopwords', methods=['GET'])
def route_get_meme_stopwords():
    """读取梗素材库停用词表（分类结构）。"""
    guard = _require_admin()
    if guard:
        return guard
    from collectors.bilibili import load_meme_stopwords
    categories = load_meme_stopwords()
    total = sum(len(v) for v in categories.values())
    return jsonify({'success': True, 'data': {'categories': categories, 'count': total}})


@app.route('/api/config/meme-stopwords', methods=['PUT'])
def route_save_meme_stopwords():
    """保存梗素材库停用词表（下次抓取生效）。"""
    from collectors.bilibili import save_meme_stopwords
    payload = request.get_json(silent=True) or {}
    categories = payload.get('categories')
    if not isinstance(categories, dict):
        return jsonify({'success': False, 'message': '参数错误：缺少 categories'}), 400
    cleaned = {}
    for cat, words in categories.items():
        if not isinstance(words, list):
            return jsonify({'success': False, 'message': f'分类 [{cat}] 格式错误'}), 400
        cleaned[cat] = [str(w).strip() for w in words if str(w).strip()]
    save_meme_stopwords(cleaned)
    total = sum(len(v) for v in cleaned.values())
    return jsonify({'success': True, 'message': f'已保存 {total} 个停用词；素材/热梗将在下次全量抓取后更新',
                    'effective': 'next_crawl'})


@app.route('/api/config/tag-filters', methods=['GET'])
def route_get_tag_filters():
    """读取标签过滤词表（is_useless_tag 共享：分类停用词/广告品牌/活动词/二字白名单）。"""
    guard = _require_admin()
    if guard:
        return guard
    from collectors.bilibili import load_tag_filters
    filters = load_tag_filters()
    total = (sum(len(v) for v in filters['categories'].values())
             + len(filters['ad_keywords']) + len(filters['activity_keywords'])
             + len(filters['allowed_two_char']))
    return jsonify({'success': True, 'data': {**filters, 'count': total}})


@app.route('/api/config/tag-filters', methods=['PUT'])
def route_save_tag_filters():
    """保存标签过滤词表（下次抓取生效）。"""
    from collectors.bilibili import save_tag_filters
    payload = request.get_json(silent=True) or {}
    categories = payload.get('categories')
    ad = payload.get('ad_keywords')
    act = payload.get('activity_keywords')
    two = payload.get('allowed_two_char')
    if not isinstance(categories, dict) or not all(isinstance(v, list) for v in categories.values()):
        return jsonify({'success': False, 'message': '参数错误：categories 需为 {分类: [词]}'}), 400
    if not all(isinstance(x, list) for x in (ad, act, two)):
        return jsonify({'success': False, 'message': '参数错误：ad_keywords/activity_keywords/allowed_two_char 需为数组'}), 400
    cleaned = {
        'categories': {k: [str(w).strip() for w in v if str(w).strip()] for k, v in categories.items()},
        'ad_keywords': [str(w).strip() for w in ad if str(w).strip()],
        'activity_keywords': [str(w).strip() for w in act if str(w).strip()],
        'allowed_two_char': [str(w).strip() for w in two if str(w).strip()],
    }
    save_tag_filters(cleaned)
    _invalidate_dashboard_payload()
    total = (sum(len(v) for v in cleaned['categories'].values())
             + len(cleaned['ad_keywords']) + len(cleaned['activity_keywords'])
             + len(cleaned['allowed_two_char']))
    return jsonify({'success': True,
                    'message': f'已保存 {total} 个过滤词；标签热度立即生效，素材派生结果下次抓取更新',
                    'effective': 'mixed'})


@app.route('/api/config/danmaku-filters', methods=['GET'])
def route_get_danmaku_filters():
    """读取弹幕热词过滤词表（filter_danmaku_words 共享：bad_exact=精确匹配、bad_substr=子串匹配）。"""
    guard = _require_admin()
    if guard:
        return guard
    from analytics.filters import load_danmaku_filters
    filters = load_danmaku_filters()
    total = len(filters.get('allowed_exact', [])) + len(filters['bad_exact']) + len(filters['bad_substr'])
    return jsonify({'success': True, 'data': {**filters, 'count': total}})


@app.route('/api/config/danmaku-filters', methods=['PUT'])
def route_save_danmaku_filters():
    """保存弹幕热词过滤词表（下次抓取生效）。"""
    from analytics.filters import save_danmaku_filters
    payload = request.get_json(silent=True) or {}
    bad_exact = payload.get('bad_exact')
    bad_substr = payload.get('bad_substr')
    allowed_exact = payload.get('allowed_exact', [])
    if not all(isinstance(x, list) for x in (allowed_exact, bad_exact, bad_substr)):
        return jsonify({'success': False, 'message': '参数错误：allowed_exact/bad_exact/bad_substr 需为数组'}), 400
    cleaned = {
        'allowed_exact': [str(w).strip() for w in allowed_exact if str(w).strip()],
        'bad_exact': [str(w).strip() for w in bad_exact if str(w).strip()],
        'bad_substr': [str(w).strip() for w in bad_substr if str(w).strip()],
    }
    save_danmaku_filters(cleaned)
    _invalidate_dashboard_payload()
    total = sum(len(cleaned[k]) for k in ('allowed_exact', 'bad_exact', 'bad_substr'))
    return jsonify({'success': True, 'message': f'已保存 {total} 条弹幕规则；词云和升温榜已立即生效',
                    'effective': 'immediate'})


@app.route('/api/config/meme-seed-words', methods=['GET'])
def route_get_meme_seed_words():
    """读取梗素材库种子热梗词列表。"""
    guard = _require_admin()
    if guard:
        return guard
    from collectors.bilibili import load_meme_seed_words
    words = load_meme_seed_words()
    return jsonify({'success': True, 'data': {'words': words, 'count': len(words)}})


@app.route('/api/config/meme-seed-words', methods=['PUT'])
def route_save_meme_seed_words():
    """保存梗素材库种子热梗词列表（下次抓取生效）。"""
    from collectors.bilibili import save_meme_seed_words
    payload = request.get_json(silent=True) or {}
    words = payload.get('words')
    if not isinstance(words, list):
        return jsonify({'success': False, 'message': '参数错误：缺少 words'}), 400
    cleaned = [str(w).strip() for w in words if str(w).strip()]
    save_meme_seed_words(cleaned)
    return jsonify({'success': True,
                    'message': f'已保存 {len(cleaned)} 个种子热梗词；将在下次全量抓取时用于主动发现',
                    'effective': 'next_crawl'})


@app.route('/api/config/word-rules/overview', methods=['GET'])
def route_word_rules_overview():
    """词汇规则中心总览：公共底座、各场景数量与真实生效方式。"""
    guard = _require_admin()
    if guard:
        return guard
    from utils.stopwords import STOPWORDS, DANMAKU_NUMERIC_ALLOWLIST
    from collectors.bilibili import load_meme_stopwords, load_meme_seed_words, load_tag_filters
    from analytics.filters import load_danmaku_filters

    meme = load_meme_stopwords()
    tag = load_tag_filters()
    danmaku = load_danmaku_filters()
    return jsonify({'success': True, 'data': {
        'common_stopwords': sorted(STOPWORDS),
        'numeric_allowlist': sorted(DANMAKU_NUMERIC_ALLOWLIST),
        'counts': {
            'common': len(STOPWORDS),
            'meme': sum(len(v) for v in meme.values()),
            'tag': (sum(len(v) for v in tag['categories'].values()) + len(tag['ad_keywords'])
                    + len(tag['activity_keywords']) + len(tag['allowed_two_char'])),
            'danmaku': (len(danmaku.get('allowed_exact', [])) + len(danmaku['bad_exact'])
                         + len(danmaku['bad_substr'])),
            'seed': len(load_meme_seed_words()),
        },
        'effects': {
            'common': '新抓取立即使用；已有弹幕榜在读取时同步过滤',
            'meme': '下次全量抓取',
            'tag': '标签热度立即重算；素材派生结果下次全量抓取',
            'danmaku': '词云与升温榜立即生效',
            'seed': '下次全量抓取',
        },
    }})


@app.route('/api/config/word-rules/test', methods=['POST'])
def route_test_word_rules():
    """用与生产榜单完全相同的入口解释词语在三个场景中的去留。"""
    from analytics.filters import explain_word
    payload = request.get_json(silent=True) or {}
    text = str(payload.get('text') or '').strip()
    if not text or len(text) > 200:
        return jsonify({'success': False, 'message': '请输入 1–200 个字符'}), 400

    # 支持一次粘贴多个词；没有分隔符时按一个完整候选词测试，避免把“哈基米”拆开。
    import re
    tokens = [w for w in re.split(r'[\s,，、;；]+', text) if w]
    results = []
    for word in tokens[:50]:
        results.append({
            'word': word,
            'scopes': {scope: explain_word(word, scope) for scope in ('meme', 'tag', 'danmaku')},
        })
    return jsonify({'success': True, 'data': {'tokens': results}})


# ==================== 开发者后台 API ====================

@app.route('/api/dev/backtest/batches', methods=['GET'])
def route_dev_backtest_batches():
    """回测面板：可回测的历史批次列表（有 potential_score 的批次）"""
    from analytics.backtest import list_scored_batches
    return jsonify({'success': True, 'data': list_scored_batches()})


@app.route('/api/dev/backtest/run', methods=['GET'])
def route_dev_backtest_run():
    """回测面板：在历史批次 T 重放评分榜单，评估对未来窗口表现的预测力"""
    from analytics.backtest import run_backtest
    try:
        ts = int(request.args.get('ts', 0))
        window = int(request.args.get('window', 48))
        top_n = int(request.args.get('top_n', 20))
    except ValueError:
        return jsonify({'success': False, 'message': '参数错误：ts/window/top_n 必须为整数'}), 400
    if not ts:
        return jsonify({'success': False, 'message': '缺少 ts 参数（历史批次时间戳）'}), 400
    return jsonify({'success': True, 'data': run_backtest(ts, window_hours=window, top_n=top_n)})


@app.route('/api/dev/stats', methods=['GET'])
def route_dev_stats():
    """数据体检：DB 健康概览（schema 版本、批次量、抓取残留等）"""
    from analytics.backtest import get_dev_stats
    return jsonify({'success': True, 'data': get_dev_stats()})


@app.route('/api/up-trends/list', methods=['GET'])
def route_up_trends_list():
    """获取互粉列表 + 增量对比（管理员工具：访客不得触发cookie爬取/看账号信息）"""
    guard = _require_admin()
    if guard:
        return guard
    user = bili_get_user_info()
    if not user:
        return jsonify({'success': False, 'message': '请先登录B站账号'}), 401

    fresh_mutuals = get_all_mutual_followings(user['mid'])
    existing = load_tracked_list()
    existing_ups = existing['ups'] if existing else []
    diff = diff_mutual_list(existing_ups, fresh_mutuals)

    return jsonify({
        'success': True,
        'data': {
            'user': user,
            'total_fresh': len(fresh_mutuals),
            'added': diff['added'],
            'removed': diff['removed'],
            'unchanged': diff['unchanged'],
            'existing_count': len(existing_ups),
        }
    })


@app.route('/api/up-trends/list', methods=['POST'])
def route_up_trends_list_save():
    """保存名单；新增或重新启用的 UP 自动进入日历基线回填队列。"""
    body = request.get_json() or {}
    ups = body.get('ups', [])
    if not isinstance(ups, list):
        return jsonify({'success': False, 'message': 'ups 必须为列表'}), 400

    previous = load_tracked_list() or {}
    old_by_mid = {}
    for up in previous.get('ups', []):
        try:
            old_by_mid[int(up.get('mid'))] = up
        except (TypeError, ValueError):
            continue

    now = int(time.time())
    normalized = []
    newly_enabled = []
    seen = set()
    for raw in ups:
        try:
            mid = int(raw.get('mid'))
        except (AttributeError, TypeError, ValueError):
            return jsonify({'success': False, 'message': '名单包含无效 mid'}), 400
        if mid <= 0 or mid in seen:
            continue
        seen.add(mid)
        old = old_by_mid.get(mid) or {}
        item = dict(raw)
        item['mid'] = mid
        item['enabled'] = bool(raw.get('enabled', True))
        # 前端不再需要负责保留系统元数据。
        item['added_at'] = old.get('added_at') or raw.get('added_at') or now
        if old.get('imported') or raw.get('imported'):
            item['imported'] = True
        normalized.append(item)
        if item['enabled'] and (not old or not old.get('enabled', True)):
            newly_enabled.append(mid)

    save_tracked_list(normalized)
    job_ids = []
    if newly_enabled:
        from jobs.calendar_jobs import enqueue_baseline_jobs
        jobs = enqueue_baseline_jobs(
            newly_enabled, requested_by=_request_actor(), reason='名单新增或重新启用',
        )
        job_ids = [job['id'] for job in jobs if job]

    return jsonify({
        'success': True,
        'message': '名单已保存',
        'count': len(normalized),
        'calendar_job_ids': job_ids,
    })


@app.route('/api/up-trends/calendar', methods=['GET'])
def route_up_trends_calendar():
    """获取发布日历热力图数据（全量 UP 聚合）
    
    与 /api/up-trends/history 的 timeline 不同：
      - history/timeline：单批次观测快照，只含该批次当时采集到的视频
      - calendar：全年全量投稿，粒度存储，随时反映当前名单
    """
    from datetime import datetime as _dt
    from storage.db import get_calendar_data, get_calendar_freshness
    from storage.tracked_ups import load_tracked_list

    tracked = load_tracked_list()
    ups = tracked.get('ups', []) if tracked else []
    # 日历只统计启用观测的 UP（disabled 的已退出观测，历史数据不再展示）。
    # 空名单传 []（而非 None），db 层返回空日历而非误显示全部 UP 的历史数据。
    mids = [u['mid'] for u in ups if u.get('enabled', True)]

    year = request.args.get('year', _dt.now().year, type=int)
    if year < 2009 or year > _dt.now().year + 1:
        return jsonify({'success': False, 'message': 'year 超出允许范围'}), 400
    data = get_calendar_data(mids=mids, year=year)

    return jsonify({
        'success': True,
        'data': data,
        'meta': {'year': year, 'fetched_at': get_calendar_freshness(mids, year)},
    })


@app.route('/api/up-trends/calendar/recent', methods=['GET'])
def route_up_trends_calendar_recent():
    """最近 N 个自然日序列；无投稿日期显式补零。"""
    from storage.db import get_calendar_recent_series

    days = request.args.get('days', 60, type=int)
    if days < 1 or days > 366:
        return jsonify({'success': False, 'message': 'days 必须在 1-366 之间'}), 400
    tracked = load_tracked_list() or {}
    mids = [u['mid'] for u in tracked.get('ups', []) if u.get('enabled', True)]
    return jsonify({'success': True, 'data': get_calendar_recent_series(mids, days)})


@app.route('/api/up-trends/calendar/day', methods=['GET'])
def route_up_trends_calendar_day():
    """某天发布的视频列表（日历点击 → 当天视频，按播放量降序）"""
    from storage.db import get_calendar_day_videos
    from storage.tracked_ups import load_tracked_list

    from datetime import datetime as _dt

    date = request.args.get('date', '')
    try:
        _dt.strptime(date, '%Y-%m-%d')
    except (TypeError, ValueError):
        return jsonify({'success': False, 'message': 'date 参数格式应为 YYYY-MM-DD'}), 400

    tracked = load_tracked_list()
    ups = tracked.get('ups', []) if tracked else []
    # 日历只统计启用观测的 UP（disabled 的已退出观测，历史数据不再展示）。
    # 空名单传 []（而非 None），db 层返回空明细而非误显示全部 UP 的视频。
    mids = [u['mid'] for u in ups if u.get('enabled', True)]

    limit = max(1, min(request.args.get('limit', 50, type=int), 100))
    videos = get_calendar_day_videos(date, mids=mids, limit=limit)
    return jsonify({'success': True, 'data': videos})


@app.route('/api/up-trends/calendar/backfill', methods=['POST'])
def route_up_trends_calendar_backfill():
    """创建持久化日历回填任务；兼容旧 days 请求格式。"""
    guard = _require_admin()
    if guard:
        return guard
    from datetime import datetime as _dt
    from jobs.calendar_jobs import enqueue_manual_calendar_job, CalendarSubmissionCooldown

    body = request.get_json(silent=True) or {}
    mode = body.get('mode')
    days = body.get('days')
    year = body.get('year')
    if not mode:
        mode = 'recent' if days is not None else 'year'
    if mode == 'recent' and days not in (7, 30):
        return jsonify({'success': False, 'message': '手动近期回填只支持 7 或 30 天'}), 400
    if mode == 'year':
        try:
            year = int(year or _dt.now().year)
        except (TypeError, ValueError):
            return jsonify({'success': False, 'message': 'year 必须为整数'}), 400
    try:
        job, created = enqueue_manual_calendar_job(
            mode=mode, days=days, year=year,
            requested_by=_request_actor(), reason='管理员手动刷新',
        )
    except CalendarSubmissionCooldown as exc:
        return jsonify({'success': False, 'message': str(exc), 'retry_after': exc.retry_after}), 429, {'Retry-After': str(exc.retry_after)}
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    return jsonify({
        'success': True,
        'message': '回填任务已创建' if created else '相同回填任务已在队列中',
        'job_id': job['id'],
        'data': job,
    }), 202


@app.route('/api/up-trends/calendar/jobs/active', methods=['GET'])
def route_calendar_job_active():
    guard = _require_admin()
    if guard:
        return guard
    from jobs.calendar_jobs import get_active_calendar_job
    return jsonify({'success': True, 'data': get_active_calendar_job()})


@app.route('/api/up-trends/calendar/jobs/<job_id>', methods=['GET'])
def route_calendar_job_status(job_id):
    guard = _require_admin()
    if guard:
        return guard
    from jobs.calendar_jobs import get_calendar_job
    job = get_calendar_job(job_id)
    if not job:
        return jsonify({'success': False, 'message': '回填任务不存在'}), 404
    return jsonify({'success': True, 'data': job})


@app.route('/api/up-trends/calendar/jobs/<job_id>/retry', methods=['POST'])
def route_calendar_job_retry(job_id):
    guard = _require_admin()
    if guard:
        return guard
    from jobs.calendar_jobs import retry_calendar_job, CalendarSubmissionCooldown
    try:
        job, created = retry_calendar_job(job_id, requested_by=_request_actor())
    except CalendarSubmissionCooldown as exc:
        return jsonify({'success': False, 'message': str(exc), 'retry_after': exc.retry_after}), 429, {'Retry-After': str(exc.retry_after)}
    if not job:
        return jsonify({'success': False, 'message': '回填任务不存在'}), 404
    if not created:
        if job['status'] in ('queued', 'running'):
            return jsonify({'success': False, 'busy': True, 'job_id': job['id'], 'message': '相同回填任务已在运行', 'data': job}), 409
        return jsonify({'success': False, 'message': '该任务没有可重试的失败 UP', 'data': job}), 409
    return jsonify({'success': True, 'job_id': job['id'], 'data': job}), 202


@app.route('/api/up-trends/list/export', methods=['GET', 'POST'])
def route_up_trends_list_export():
    """导出当前关注名单为 JSON 文件下载。

    数据来源优先级（避免持久名单暂时为空时导出空文件）：
      1. POST body 携带的 ups
      2. PostgreSQL 持久化名单
      3. up_obs 最新批次 up_details 兜底
    """
    import json as _json
    from io import BytesIO

    def _normalize(up):
        return {
            'mid': up.get('mid'),
            'name': up.get('name', ''),
            'face': up.get('face', ''),
            'follower_count': up.get('follower_count', 0),
            'enabled': up.get('enabled', True),
        }

    ups = []
    source_label = ''

    if request.method == 'POST':
        body = request.get_json(silent=True) or {}
        body_ups = body.get('ups', [])
        if isinstance(body_ups, list) and body_ups:
            ups = body_ups
            source_label = 'post'

    if not ups:
        tracked = load_tracked_list()
        if tracked and tracked.get('ups'):
            ups = tracked['ups']
            source_label = 'tracked_file'

    if not ups:
        # fallback 从 up_obs 最新批次恢复（数据源更可靠，且与读路径一致）
        ts = get_latest_batch_ts()
        if ts:
            ups = get_up_details(ts)
            source_label = 'up_obs_fallback'

    if not ups:
        return jsonify({
            'success': False,
            'message': '名单为空：持久化名单为空且无历史分析数据可恢复，请先配置关注名单'
        }), 400

    export_data = {
        'format': 'kichu-board-tracked-ups',
        'version': 1,
        'exported_at': int(time.time()),
        'source': source_label,
        'count': len(ups),
        'ups': [_normalize(up) for up in ups],
    }

    buf = BytesIO()
    buf.write(_json.dumps(export_data, ensure_ascii=False, indent=2).encode('utf-8'))
    buf.seek(0)

    count = len(ups)
    ts_str = time.strftime("%Y%m%d_%H%M%S")
    filename = f'关注名单_{count}人_{ts_str}.json'
    return send_file(buf, as_attachment=True, download_name=filename, mimetype='application/json')


@app.route('/api/up-trends/list/import', methods=['POST'])
def route_up_trends_list_import():
    """导入关注名单，按 mid 合并去重。"""
    body = request.get_json() or {}
    import_ups = body.get('ups', [])

    if not import_ups:
        return jsonify({'success': False, 'message': '导入数据为空'}), 400

    if isinstance(import_ups, dict) and 'ups' in import_ups:
        import_ups = import_ups['ups']
    if not isinstance(import_ups, list):
        return jsonify({'success': False, 'message': '格式错误：ups 应为列表'}), 400

    tracked = load_tracked_list()
    existing_ups = tracked['ups'] if tracked else []
    existing_mids = set()
    for existing_up in existing_ups:
        try:
            existing_mids.add(int(existing_up.get('mid')))
        except (TypeError, ValueError):
            continue

    added = 0
    skipped = 0
    added_mids = []
    for up in import_ups:
        try:
            mid = int(up.get('mid'))
        except (AttributeError, TypeError, ValueError):
            skipped += 1
            continue
        if mid <= 0:
            skipped += 1
            continue
        if mid in existing_mids:
            skipped += 1
        else:
            existing_ups.append({
                'mid': mid,
                'name': up.get('name', ''),
                'face': up.get('face', ''),
                'follower_count': up.get('follower_count', 0),
                'enabled': up.get('enabled', True),
                'added_at': int(time.time()),
                'imported': True,
            })
            added += 1
            existing_mids.add(mid)
            if up.get('enabled', True):
                added_mids.append(mid)

    save_tracked_list(existing_ups)
    job_ids = []
    if added_mids:
        from jobs.calendar_jobs import enqueue_baseline_jobs
        jobs = enqueue_baseline_jobs(
            added_mids, requested_by=_request_actor(), reason='名单导入新增 UP',
        )
        job_ids = [job['id'] for job in jobs if job]

    return jsonify({
        'success': True,
        'message': f'导入完成：新增 {added} 个，跳过 {skipped} 个已存在',
        'added': added,
        'skipped': skipped,
        'total': len(existing_ups),
        'calendar_job_ids': job_ids,
    })


@app.route('/api/up-trends/check', methods=['GET'])
def route_up_trends_check():
    """健康检查：has_list 查名单配置，has_analysis 查 up_obs 是否有数据"""
    try:
        return jsonify({
            'success': True,
            'has_list': has_tracked_list(),
            'has_analysis': get_latest_batch_ts() is not None,
            'active_task_id': get_running_task_id(),
        })
    except Exception:
        app.logger.exception('UP analysis configuration query failed')
        return jsonify({'success': False, 'code': 'analysis_queue_unavailable', 'message': '任务队列暂不可用，请稍后重新连接'}), 503


@app.route('/api/up-trends/analysis', methods=['GET'])
def route_up_trends_analysis():
    """读取最新分析缓存（秒开）

    完全走数据库（up_obs + video_obs_snapshot）。
    返回数据多 _read_from / _up_obs_ts 两个调试字段，前端可忽略。
    """
    result = load_analysis()
    if result:
        return jsonify({'success': True, 'data': result, 'from_cache': True})
    return jsonify({
        'success': False,
        'message': '暂无分析数据，请先配置名单并刷新',
    }), 404


@app.route('/api/up-trends/up-card/<int:mid>', methods=['GET'])
def route_up_trends_up_card(mid):
    """UP 卡片数据：词云 + 分区 top3 + 统计（列表内联标签 / 悬停弹窗共用）。

    数据来自 get_up_card（arc/search 翻页拉全量投稿），带 1 天 DB 缓存，
    首次请求翻页较慢（秒级），命中缓存后秒回。
    """
    from collectors.bilibili_user import get_up_card
    card = get_up_card(mid)
    if not card:
        return jsonify({'success': False, 'message': f'获取 UP {mid} 卡片数据失败（可能无投稿或接口异常）'}), 502
    return jsonify({'success': True, 'data': card})


@app.route('/api/up-trends/refresh', methods=['POST'])
def route_up_trends_refresh():
    """刷新选中UP主的分析数据（后台任务，返回task_id）"""
    tracked = load_tracked_list()
    if not tracked or not tracked['ups']:
        return jsonify({'success': False, 'message': '请先配置关注的UP主名单'}), 400

    enabled_ups = [u for u in tracked['ups'] if u.get('enabled', True)]
    if not enabled_ups:
        return jsonify({'success': False, 'message': '没有已启用的UP主'}), 400

    try:
        task_id = start_analysis(enabled_ups, requested_by=_request_actor())
        running_id = get_running_task_id() if task_id is None else None
    except Exception:
        app.logger.exception('UP analysis task submission failed')
        return jsonify({'success': False, 'code': 'analysis_queue_unavailable', 'message': '任务提交失败，请稍后重试'}), 503
    # 执行锁未抢到（已有分析在跑）→ 409，但把当前在跑的 task_id 一并返回，
    # 前端可直接接管轮询该任务，避免用户双击导致体验断链
    if task_id is None:
        return jsonify({
            'success': False,
            'message': '已有分析任务正在运行，已切换到该任务进度',
            'busy': True,
            'task_id': running_id,   # 可能为 None（极端：刚跑完被清理），前端兜底
        }), 409
    return jsonify({
        'success': True,
        'task_id': task_id,
        'total': len(enabled_ups),
    })


@app.route('/api/up-trends/progress', methods=['GET'])
def route_up_trends_progress():
    """查询分析任务进度"""
    task_id = request.args.get('task_id', '')
    if not task_id:
        return jsonify({'success': False, 'message': '缺少task_id'}), 400

    try:
        progress = get_progress(task_id)
    except Exception:
        app.logger.exception('UP analysis progress query failed')
        return jsonify({'success': False, 'code': 'analysis_queue_unavailable', 'message': '任务进度暂不可用，请稍后重新连接'}), 503
    if not progress:
        return jsonify({'success': False, 'code': 'task_not_found', 'message': '任务不存在'}), 404

    return jsonify({'success': True, 'data': progress})


@app.route('/api/up-trends/history', methods=['GET'])
def route_up_trends_history():
    """获取历史趋势数据（用于趋势图）

    合并 video_obs_snapshot（timeline）与 up_obs（summary + play_ranking），
    返回前端 TrendCharts 可直接消费的 batches。
    """
    import time as _time
    tracked = load_tracked_list()
    tracked_count = len(tracked['ups']) if tracked else 0

    days = request.args.get('days', 30, type=int)
    end_ts = int(_time.time())
    start_ts = end_ts - days * 86400
    batches = load_history_batches(start_ts, end_ts)

    return jsonify({
        'success': True,
        'data': {
            'batches': batches,
            'tracked_count': tracked_count,
        }
    })


@app.route('/api/videos/<bvid>/obs-trend', methods=['GET'])
def route_video_obs_trend(bvid):
    """获取单个视频近 N 小时的观测时序数据（用于 VideoCard 折线图）。

    返回 video_obs 时序点，含播放量/点赞/同接等指标，前端按需叠加展示。
    """
    from storage.db import get_video_obs_trend
    hours = request.args.get('hours', 48, type=int)
    hours = max(1, min(hours, 168))  # 限制范围，避免恶意超大查询
    points = get_video_obs_trend(bvid, hours)
    return jsonify({
        'success': True,
        'data': {
            'points': points,
            'count': len(points),
        }
    })


@app.route('/api/videos/<bvid>/conclusion', methods=['GET'])
def route_video_conclusion(bvid):
    """获取视频 AI 总结（B站官方 AI 生成的摘要 + 大纲）。

    需要登录态（WBI 签名）。返回 summary + outline 两大字段。
    """
    from collectors.bilibili import fetch_video_conclusion
    result = fetch_video_conclusion(bvid)
    return jsonify({
        'success': result.get('success', False),
        'data': {
            'summary': result.get('summary', ''),
            'outline': result.get('outline', []),
        },
        'message': result.get('message', ''),
    })


@app.route('/api/bursting-videos', methods=['GET'])
def route_bursting_videos():
    """播放量增速榜 + 爆发预警（仅 hot tier，近 2 小时窗口）。"""
    from storage.db import get_bursting_videos
    window = request.args.get('window', 2, type=int)
    threshold = request.args.get('threshold', 2.0, type=float)
    limit = request.args.get('limit', 20, type=int)
    videos = get_bursting_videos(
        window_hours=max(1, min(window, 12)),
        threshold=max(1.0, min(threshold, 10.0)),
        limit=max(1, min(limit, 50)),
    )
    # 从缓存补充封面图和 UP 主信息（DB 的 videos 表不存 pic/owner）
    # 注：缓存里的视频字段是 cover/author（parse_video_item/parse_region_rank_item 返回），
    # 而前端 BurstingVideos 期望 pic/owner.name，这里做字段映射。
    try:
        from storage.cache import get_data
        cache = get_data()
        vid_map = {}
        for key in ('kichu_rank', 'hot_videos', 'material_candidates', 'hot_songs', 'meme_materials'):
            for v in cache.get(key, []):
                if v.get('bvid'):
                    vid_map[v['bvid']] = {
                        'pic': v.get('cover') or v.get('pic'),
                        'owner_name': v.get('author') or (v.get('owner') or {}).get('name') if isinstance(v.get('owner'), dict) else v.get('owner'),
                    }
        for v in videos:
            info = vid_map.get(v['bvid'])
            if info:
                if info['pic']:
                    v['pic'] = info['pic']
                if info['owner_name'] and not (v.get('owner') and v['owner'].get('name')):
                    v['owner'] = {'name': info['owner_name']}
    except Exception:
        pass  # 缓存补充失败不影响增速榜核心功能

    return jsonify({
        'success': True,
        'data': {
            'videos': videos,
            'count': len(videos),
            'window_hours': window,
            'threshold': threshold,
        }
    })


@app.route('/api/videos/interaction-quality', methods=['GET'])
def route_interaction_quality():
    """互动质量榜：低播放高互动的宝藏视频（选材信号）。

    只显示发布于近 14 天的视频。复用 radar-v2 的同龄样本分位口径：
    点赞、投币、收藏、分享、评论、弹幕六项分位分等权平均。
    缺少可信观测或有效基线时保留候选，但不伪造得分。
    """
    from storage.db import get_interaction_quality
    limit = request.args.get('limit', 20, type=int)
    items = get_interaction_quality(limit=max(1, min(limit, 50)))
    # 补充 UP 名：DB 的 videos 表不存作者，ups 表仅含关注名单，从看板缓存按 bvid 补齐
    try:
        from storage.cache import get_data
        cache = get_data()
        author_map = {}
        for key in ('kichu_rank', 'hot_videos', 'material_candidates', 'hot_songs', 'meme_materials'):
            for v in cache.get(key, []):
                if v.get('bvid'):
                    author = v.get('author')
                    if not author and isinstance(v.get('owner'), dict):
                        author = v.get('owner', {}).get('name')
                    if author:
                        author_map[v['bvid']] = author
        for v in items:
            if not v.get('author'):
                v['author'] = author_map.get(v['bvid'], '')
    except Exception:
        pass  # 作者名补充失败不影响互动质量榜核心功能
    return jsonify({'success': True, 'data': items})


@app.route('/api/up-trends/publish-habits', methods=['GET'])
def route_up_trends_publish_habits():
    """发布习惯：按小时/星期聚合发布量与平均播放（指导发稿时机）。

    范围：当前关注名单 UP（calendar_videos 全量投稿），近 days 天窗口。
    """
    from storage.db import get_publish_habits
    from storage.tracked_ups import load_tracked_list
    tracked = load_tracked_list()
    ups = tracked.get('ups', []) if tracked else []
    # 与日历一致：只统计启用观测的 UP；空名单传 []（而非 None），db 层返回空
    mids = [u['mid'] for u in ups if u.get('enabled', True)]
    days = request.args.get('days', 180, type=int)
    data = get_publish_habits(mids=mids, days=max(30, min(days, 730)))
    return jsonify({'success': True, 'data': data})


@app.route('/api/up-trends/follower-growth', methods=['GET'])
def route_follower_growth():
    """涨粉榜：最新批次 vs 窗口起点批次的粉丝数差值（识别涨粉最快的UP）。

    数据：up_obs 时序（每批次含 follower_count）。
    """
    from storage.db import get_follower_growth
    days = request.args.get('days', 7, type=int)
    limit = request.args.get('limit', 10, type=int)
    data = get_follower_growth(
        days=max(1, min(days, 90)),
        limit=max(1, min(limit, 30)),
    )
    return jsonify({'success': True, 'data': data})


@app.route('/api/up-trends/hot-growth', methods=['GET'])
def route_up_trends_hot_growth():
    """高增速视频榜：追踪 UP 主视频中播放量增速最快的（跨批次快照对比）。

    数据：video_obs_snapshot 的 all_videos（新批次全量）/ hot_videos（老批次 TOP10 兜底）。
    增速 = 最新观测 vs 上一次观测的播放增量 / 间隔小时。
    """
    from storage.video_snapshot_reader import get_hot_growth_videos
    lookback = request.args.get('lookback', 14, type=int)
    limit = request.args.get('limit', 10, type=int)
    data = get_hot_growth_videos(
        lookback_days=max(1, min(lookback, 90)),
        limit=max(1, min(limit, 30)),
    )
    return jsonify({'success': True, 'data': data})


@app.route('/api/videos/tag-heat', methods=['GET'])
def route_tag_heat():
    """标签热度：鬼畜分区视频标签频次 + 平均播放/互动，爆款标签标记。

    数据：video_tags + videos（鬼畜分区）+ video_obs（最新互动）。
    """
    from storage.db import get_tag_heat
    limit = request.args.get('limit', 30, type=int)
    data = get_tag_heat(limit=max(5, min(limit, 100)))
    return jsonify({'success': True, 'data': data})


@app.route('/api/danmaku/rising-words', methods=['GET'])
def route_rising_words():
    """弹幕热词升温榜：最近批次 vs 基准批次的标准化出现率。

    数据：word_obs（弹幕热词批次观测）。
    """
    from storage.db import get_rising_words
    recent_batches = request.args.get('recent_batches', 2, type=int)
    base_batches = request.args.get('base_batches', 6, type=int)
    limit = request.args.get('limit', 30, type=int)
    data, meta = get_rising_words(
        recent_batches=max(1, min(recent_batches, 12)),
        base_batches=max(1, min(base_batches, 30)),
        limit=max(5, min(limit, 100)),
        return_meta=True,
    )
    return jsonify({'success': True, 'data': data, 'meta': meta})


@app.route('/api/up-trends', methods=['GET'])
def route_up_trends():
    """兼容旧接口（走数据库读层 load_analysis）"""
    if not has_tracked_list():
        return jsonify({
            'success': False,
            'need_setup': True,
            'message': '请先配置关注的UP主名单',
        })

    result = load_analysis()
    if result:
        return jsonify({'success': True, 'data': result, 'from_cache': True})

    return jsonify({
        'success': True,
        'data': None,
        'has_list': True,
        'message': '名单已配置，点击刷新获取最新动态',
    })


# ==================== 入口 ====================

if __name__ == '__main__':
    setup_logging()
    from logger import get_logger
    logger = get_logger(__name__)

    logger.info('鬼畜热度看板 V3.0 - 本地 API 服务启动中...')

    app.run(host='0.0.0.0', port=BACKEND_PORT, debug=False, threaded=True)
