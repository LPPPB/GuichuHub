"""身份存储层 — 管理员名单 + B站登录会话（SQLite auth.db）

独立于 kichu_board.db（时序数据）与 inspiration_db.json（收藏）：
权限数据单独成库，方便测试隔离（monkeypatch AUTH_DB_PATH 即可）与整体备份/清除。

表结构：
  admin_accounts  管理员名单（B站 mid → 站长授权的管理员）
  bili_sessions   访客B站登录会话（凭证只落此处，浏览器仅持 token）
  collector_credential_handoffs  管理员授权、Worker 消费的采集凭证动作

安全约定：
  - cookies 字段（SESSDATA/bili_jct 明文）绝不出本模块以外的 API 响应；
    app 层拿 token 换身份，不回传凭证。
  - 会话 30 天过期；同浏览器重新登录替换旧会话（单浏览器单账号）。
  - 删除保护：名单只剩一人时拒绝删除（防自锁，超管口令可再救回）。
"""

import os
import json
import secrets
import sqlite3
import threading
import time
from runtime_paths import RuntimePaths

RUNTIME_PATHS = RuntimePaths.from_environment(os.environ)
DATA_DIR = str(RUNTIME_PATHS.auth_db.parent)
AUTH_DB_PATH = str(RUNTIME_PATHS.auth_db)

SESSION_TTL = 30 * 24 * 3600  # 会话有效期：30 天

_thread_local = threading.local()
_auth_repository = None


def configure_auth_repository(repository):
    """Install the PostgreSQL authentication repository for public adapters."""
    global _auth_repository
    _auth_repository = repository


def _conn():
    """当前线程连接；AUTH_DB_PATH 变化（测试 monkeypatch）时自动重连。"""
    path = AUTH_DB_PATH
    conn = getattr(_thread_local, 'conn', None)
    if conn is not None and getattr(_thread_local, 'db_path', None) == path:
        return conn
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=5000')
    _init_schema(conn)
    _thread_local.conn = conn
    _thread_local.db_path = path
    return conn


def _init_schema(conn):
    conn.execute('''
        CREATE TABLE IF NOT EXISTS admin_accounts (
            mid      INTEGER PRIMARY KEY,
            name     TEXT DEFAULT '',
            face     TEXT DEFAULT '',
            added_at INTEGER NOT NULL,
            added_by TEXT DEFAULT ''
        )''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS bili_sessions (
            token       TEXT PRIMARY KEY,
            visitor_id  TEXT NOT NULL,
            mid         INTEGER,
            name        TEXT DEFAULT '',
            face        TEXT DEFAULT '',
            cookies     TEXT DEFAULT '',
            created_at  INTEGER NOT NULL,
            expires_at  INTEGER NOT NULL
        )''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_sessions_visitor ON bili_sessions(visitor_id)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_sessions_mid ON bili_sessions(mid)')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS collector_credential_handoffs (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            action       TEXT NOT NULL CHECK(action IN ('replace', 'delete')),
            payload      TEXT NOT NULL DEFAULT '',
            requested_by TEXT NOT NULL,
            requested_at INTEGER NOT NULL
        )''')
    conn.commit()


# ==================== 管理员名单 ====================

def admin_count():
    if _auth_repository is not None:
        return _auth_repository.admin_count()
    return _conn().execute('SELECT COUNT(*) FROM admin_accounts').fetchone()[0]


def list_admin_accounts():
    if _auth_repository is not None:
        return _auth_repository.list_admin_accounts()
    rows = _conn().execute(
        'SELECT mid, name, face, added_at, added_by FROM admin_accounts ORDER BY added_at').fetchall()
    return [dict(r) for r in rows]


def is_admin_mid(mid):
    if mid is None:
        return False
    try:
        mid = int(mid)
    except (TypeError, ValueError):
        return False
    if _auth_repository is not None:
        return _auth_repository.is_admin_mid(mid)
    return _conn().execute(
        'SELECT 1 FROM admin_accounts WHERE mid = ?', (mid,)).fetchone() is not None


def add_admin_account(mid, name='', face='', added_by=''):
    """添加管理员。返回 (row, err)：err ∈ {None, 'INVALID', 'EXISTS'}"""
    try:
        mid = int(mid)
    except (TypeError, ValueError):
        return None, 'INVALID'
    if mid <= 0:
        return None, 'INVALID'
    if _auth_repository is not None:
        return _auth_repository.add_admin_account(
            mid, str(name or ''), str(face or ''), str(added_by or ''), int(time.time()),
        )
    conn = _conn()
    if conn.execute('SELECT 1 FROM admin_accounts WHERE mid = ?', (mid,)).fetchone():
        return None, 'EXISTS'
    now = int(time.time())
    conn.execute(
        'INSERT INTO admin_accounts (mid, name, face, added_at, added_by) VALUES (?,?,?,?,?)',
        (mid, str(name or ''), str(face or ''), now, str(added_by or '')))
    conn.commit()
    return {'mid': mid, 'name': name or '', 'face': face or '',
            'added_at': now, 'added_by': added_by or ''}, None


def remove_admin_account(mid):
    """删除管理员（最后一名保护）。返回 (ok, err)：err ∈ {None, 'NOT_FOUND', 'LAST_ADMIN'}"""
    try:
        mid = int(mid)
    except (TypeError, ValueError):
        return False, 'NOT_FOUND'
    if _auth_repository is not None:
        return _auth_repository.remove_admin_account(mid)
    conn = _conn()
    if not conn.execute('SELECT 1 FROM admin_accounts WHERE mid = ?', (mid,)).fetchone():
        return False, 'NOT_FOUND'
    if admin_count() <= 1:
        return False, 'LAST_ADMIN'
    conn.execute('DELETE FROM admin_accounts WHERE mid = ?', (mid,))
    conn.commit()
    return True, None


def update_admin_profile(mid, name, face):
    """登录时回写名单内账号的昵称头像（资料自愈，不在名单则 no-op）"""
    try:
        mid = int(mid)
    except (TypeError, ValueError):
        return False
    if not name and not face:
        return False
    if _auth_repository is not None:
        return _auth_repository.update_admin_profile(mid, str(name or ''), str(face or ''))
    conn = _conn()
    row = conn.execute('SELECT 1 FROM admin_accounts WHERE mid = ?', (mid,)).fetchone()
    if not row:
        return False
    conn.execute('UPDATE admin_accounts SET name = ?, face = ? WHERE mid = ?',
                 (str(name or ''), str(face or ''), mid))
    conn.commit()
    return True


# ==================== B站登录会话 ====================

def create_session(visitor_id, mid, name, face, cookies):
    """为访客签发会话 token；同访客旧会话一并作废（单浏览器单账号）。

    cookies（含 SESSDATA/bili_jct）以 JSON 明文落库，仅服务器内部使用。
    """
    now = int(time.time())
    if _auth_repository is not None:
        return _auth_repository.create_session(visitor_id, mid, name, face, cookies, now)

    token = secrets.token_hex(24)
    cookies_json = ''
    try:
        import json
        cookies_json = json.dumps(cookies or {}, ensure_ascii=False)
    except Exception:
        cookies_json = '{}'
    conn = _conn()
    conn.execute('DELETE FROM bili_sessions WHERE visitor_id = ?', (visitor_id,))
    conn.execute(
        'INSERT INTO bili_sessions (token, visitor_id, mid, name, face, cookies, created_at, expires_at) '
        'VALUES (?,?,?,?,?,?,?,?)',
        (token, visitor_id, mid, str(name or ''), str(face or ''), cookies_json, now, now + SESSION_TTL))
    conn.commit()
    return token


def get_session(token):
    """按 token 取会话；过期/不存在返回 None（过期即清除）。"""
    if not token or not isinstance(token, str) or len(token) > 128:
        return None
    if _auth_repository is not None:
        return _auth_repository.get_session(token, int(time.time()))
    conn = _conn()
    row = conn.execute('SELECT * FROM bili_sessions WHERE token = ?', (token,)).fetchone()
    if row is None:
        return None
    if row['expires_at'] < time.time():
        conn.execute('DELETE FROM bili_sessions WHERE token = ?', (token,))
        conn.commit()
        return None
    out = dict(row)
    out.pop('cookies', None)  # 凭证不离开存储层
    return out


def delete_session(token):
    """登出：销毁会话（凭证随行删除）。返回是否删除了有效会话。"""
    if not token:
        return False
    conn = _conn()
    cur = conn.execute('DELETE FROM bili_sessions WHERE token = ?', (token,))
    conn.commit()
    return cur.rowcount > 0


def list_recent_logins(limit=10):
    """最近登录的不同B站账号（供管理员"一键添加"参考）。"""
    conn = _conn()
    rows = conn.execute(
        'SELECT mid, name, face, MAX(created_at) AS last_login '
        'FROM bili_sessions GROUP BY mid ORDER BY last_login DESC LIMIT ?', (limit,)).fetchall()
    return [dict(r) for r in rows]


def purge_expired_sessions():
    """清理过期会话。返回清理条数（调度层可定期调用）。"""
    conn = _conn()
    cur = conn.execute('DELETE FROM bili_sessions WHERE expires_at < ?', (int(time.time()),))
    conn.commit()
    return cur.rowcount


# ==================== 采集凭证交接队列 ====================

def request_collector_cookie_update(cookies, requested_by):
    """记录管理员已授权的采集凭证更新，由 Worker 持久化到私有 Cookie 文件。"""
    if not requested_by:
        raise ValueError('collector handoff requires an authenticated requester')
    payload = json.dumps(cookies or {}, ensure_ascii=False)
    conn = _conn()
    cur = conn.execute(
        'INSERT INTO collector_credential_handoffs '
        '(action, payload, requested_by, requested_at) VALUES (?,?,?,?)',
        ('replace', payload, str(requested_by), int(time.time())))
    conn.commit()
    return cur.lastrowid


def request_collector_logout(requested_by):
    """记录管理员已授权的采集账号退出，由 Worker 删除私有 Cookie 文件。"""
    if not requested_by:
        raise ValueError('collector handoff requires an authenticated requester')
    conn = _conn()
    cur = conn.execute(
        'INSERT INTO collector_credential_handoffs '
        '(action, payload, requested_by, requested_at) VALUES (?,?,?,?)',
        ('delete', '', str(requested_by), int(time.time())))
    conn.commit()
    return cur.lastrowid


def get_pending_collector_action():
    """返回最早的待处理动作；Worker 成功处理前记录保持持久。"""
    row = _conn().execute(
        'SELECT id, action, payload, requested_by, requested_at '
        'FROM collector_credential_handoffs ORDER BY id LIMIT 1').fetchone()
    return dict(row) if row is not None else None


def complete_collector_action(action_id):
    """仅在 Worker 完成幂等文件操作后确认并删除队列记录。"""
    conn = _conn()
    cur = conn.execute(
        'DELETE FROM collector_credential_handoffs WHERE id = ?', (int(action_id),))
    conn.commit()
    return cur.rowcount > 0
