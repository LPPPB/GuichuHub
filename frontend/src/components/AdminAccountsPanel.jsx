import { useState, useEffect, useCallback } from 'react'
import { api } from '../utils/api'
import BilibiliLogin from './BilibiliLogin'
import {
  ShieldCheck, Trash2, Plus, RefreshCw, LogIn, LogOut, User, Info, UserCog, Camera,
} from 'lucide-react'

// 开发者后台 · 管理员管理：
//   1. 管理员名单（B站账号 mid 判定）：添加 / 删除（后端保底"至少保留一名"）
//   2. 最近扫码登录：快速把已登录账号提升为管理员
//   3. 采集账号：爬虫专用 Cookie 状态与登录/退出（与管理员身份解耦）
const fmtTime = (ts) => {
  if (!ts) return '-'
  const d = new Date(ts * 1000)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export default function AdminAccountsPanel() {
  const [accounts, setAccounts] = useState([])
  const [recentLogins, setRecentLogins] = useState([])
  const [loading, setLoading] = useState(true)
  const [notice, setNotice] = useState('')      // 操作反馈（auto-dismiss）
  const [noticeType, setNoticeType] = useState('ok')
  const [newMid, setNewMid] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [removingMid, setRemovingMid] = useState(null)

  // 采集账号（管理员专属接口；非管理员/未登录时为 null）
  const [collectUser, setCollectUser] = useState(null)
  const [collectChecked, setCollectChecked] = useState(false)
  const [showCollectLogin, setShowCollectLogin] = useState(false)

  const flash = (msg, type = 'ok') => {
    setNotice(msg)
    setNoticeType(type)
    setTimeout(() => setNotice(''), 4000)
  }

  const load = useCallback(async () => {
    setLoading(true)
    const res = await api.adminAccounts()
    if (res.success && res.data) {
      setAccounts(res.data.accounts || [])
      setRecentLogins(res.data.recent_logins || [])
    } else {
      flash(res.message || '加载管理员名单失败', 'err')
    }
    setLoading(false)
  }, [])

  const loadCollect = useCallback(async () => {
    const res = await api.getUserInfo()
    setCollectUser(res.success && res.data ? res.data : null)
    setCollectChecked(true)
  }, [])

  useEffect(() => { load(); loadCollect() }, [load, loadCollect])

  const handleAdd = async () => {
    const mid = newMid.trim()
    if (!mid || !/^\d+$/.test(mid)) { flash('请输入纯数字的 B站 UID', 'err'); return }
    setSubmitting(true)
    const res = await api.addAdminAccount(Number(mid))
    setSubmitting(false)
    if (res.success) {
      flash(`已添加管理员 ${res.data?.name || `UID ${mid}`}`)
      setNewMid('')
      load()
    } else {
      flash(res.message || '添加失败', 'err')
    }
  }

  const handleRemove = async (mid, name) => {
    const label = name || `UID ${mid}`
    if (!window.confirm(`确认移除管理员 ${label}？移除后该账号扫码登录将变为普通访客。`)) return
    setRemovingMid(mid)
    const res = await api.removeAdminAccount(mid)
    setRemovingMid(null)
    if (res.success) { flash(`已移除 ${label}`); load() }
    else flash(res.message || '移除失败', 'err')
  }

  const handleCollectLoginSuccess = async () => {
    await loadCollect()
    flash('采集账号已登录，爬虫将使用新凭证')
  }

  const handleCollectLogout = async () => {
    const res = await api.collectLogout()
    if (res.success) { setCollectUser(null); flash('采集账号已退出') }
    else flash(res.message || '退出失败', 'err')
  }

  const Avatar = ({ face, name, size = 28 }) => (
    <div className="shrink-0 rounded-full bg-slate-100 overflow-hidden flex items-center justify-center"
         style={{ width: size, height: size }}>
      {face
        ? <img src={`/api/proxy/image?url=${encodeURIComponent(face)}`} alt={name}
               className="w-full h-full object-cover" onError={(e) => { e.target.style.display = 'none' }} />
        : <User size={size * 0.5} className="text-slate-400" />}
    </div>
  )

  return (
    <div className="space-y-5">
      {/* 操作反馈条 */}
      {notice && (
        <div className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium ${
          noticeType === 'ok' ? 'bg-emerald-50 text-emerald-700 border border-emerald-200' : 'bg-rose-50 text-rose-700 border border-rose-200'
        }`}>
          {noticeType === 'ok' ? <ShieldCheck size={15} /> : <Info size={15} />}
          {notice}
        </div>
      )}

      {/* ── 管理员名单 ── */}
      <section className="bg-white border border-slate-200 rounded-2xl p-5">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-base font-bold text-slate-800 flex items-center gap-2">
            <ShieldCheck size={18} className="text-primary-500" />管理员名单
          </h3>
          <button onClick={load} disabled={loading}
                  className="flex items-center gap-1.5 text-xs text-slate-500 hover:text-slate-700 disabled:opacity-40">
            <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />刷新
          </button>
        </div>
        <p className="text-xs text-slate-500 -mt-2 mb-4 flex items-start gap-1.5">
          <Info size={13} className="shrink-0 mt-0.5" />
          名单内B站账号扫码登录即视为管理员（审核申请 / 刷新数据 / 词表配置）；至少保留一名，防止自锁。
        </p>

        {/* 添加表单 */}
        <div className="flex gap-2 mb-4">
          <input
            value={newMid}
            onChange={(e) => setNewMid(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !submitting) handleAdd() }}
            placeholder="输入 B站 UID（数字），如 3494368446315382"
            inputMode="numeric"
            className="flex-1 px-3.5 py-2 text-sm border border-slate-300 rounded-xl focus:outline-none focus:ring-2 focus:ring-primary-400 focus:border-primary-400"
          />
          <button onClick={handleAdd} disabled={submitting || !newMid.trim()}
                  className="flex items-center gap-1.5 px-4 py-2 text-sm font-semibold text-white
                             bg-primary-500 hover:bg-primary-600 disabled:opacity-40 disabled:cursor-not-allowed
                             rounded-xl transition-colors">
            <Plus size={15} />{submitting ? '添加中…' : '添加管理员'}
          </button>
        </div>

        {/* 名单列表 */}
        {loading ? (
          <p className="text-sm text-slate-400 text-center py-8">加载中…</p>
        ) : accounts.length === 0 ? (
          <p className="text-sm text-slate-400 text-center py-8">名单为空（当前仅写口令超管可用）</p>
        ) : (
          <ul className="divide-y divide-slate-100">
            {accounts.map((a) => (
              <li key={a.mid} className="flex items-center gap-3 py-3">
                <Avatar face={a.face} name={a.name} />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-semibold text-slate-800 truncate">{a.name || `UID ${a.mid}`}</p>
                  <p className="text-xs text-slate-400 truncate">
                    UID {a.mid} · 添加于 {fmtTime(a.added_at)}{a.added_by ? ` · 由 ${a.added_by}` : ''}
                  </p>
                </div>
                <button onClick={() => handleRemove(a.mid, a.name)} disabled={removingMid === a.mid}
                        title="移除管理员"
                        className="p-2 rounded-lg text-slate-400 hover:text-rose-600 hover:bg-rose-50
                                   disabled:opacity-40 transition-colors">
                  <Trash2 size={15} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* ── 最近扫码登录 ── */}
      <section className="bg-white border border-slate-200 rounded-2xl p-5">
        <h3 className="text-base font-bold text-slate-800 flex items-center gap-2 mb-1">
          <UserCog size={18} className="text-primary-500" />最近扫码登录
        </h3>
        <p className="text-xs text-slate-500 mb-4 flex items-start gap-1.5">
          <Info size={13} className="shrink-0 mt-0.5" />
          近期在本站扫码过的B站账号；点击可快速补录进管理员名单。
        </p>
        {recentLogins.length === 0 ? (
          <p className="text-sm text-slate-400 text-center py-6">暂无登录记录</p>
        ) : (
          <ul className="divide-y divide-slate-100">
            {recentLogins.map((r) => (
              <li key={`${r.mid}-${r.created_at || ''}`} className="flex items-center gap-3 py-2.5">
                <Avatar face={r.face} name={r.name} size={24} />
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-slate-700 truncate">
                    {r.name || `UID ${r.mid}`}
                    {r.is_admin && (
                      <span className="ml-1.5 inline-flex items-center gap-0.5 px-1.5 py-[1px] rounded-full
                                       text-[10px] font-semibold bg-primary-50 text-primary-600">
                        <ShieldCheck size={9} />管理员
                      </span>
                    )}
                  </p>
                  <p className="text-xs text-slate-400 truncate">UID {r.mid} · {fmtTime(r.created_at || r.last_active)}</p>
                </div>
                {!r.is_admin && (
                  <button onClick={() => { setNewMid(String(r.mid)); }}
                          title="填入上方添加表单"
                          className="text-xs text-primary-600 hover:text-primary-700 font-medium
                                     px-2.5 py-1.5 rounded-lg hover:bg-primary-50 transition-colors">
                    填入UID
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* ── 采集账号 ── */}
      <section className="bg-white border border-slate-200 rounded-2xl p-5">
        <h3 className="text-base font-bold text-slate-800 flex items-center gap-2 mb-1">
          <Camera size={18} className="text-primary-500" />采集账号（爬虫凭证）
        </h3>
        <p className="text-xs text-slate-500 mb-4 flex items-start gap-1.5">
          <Info size={13} className="shrink-0 mt-0.5" />
          服务器爬虫采集数据所用账号，与管理员身份相互独立；凭证只存服务器文件，不进浏览器。
        </p>
        {!collectChecked ? (
          <p className="text-sm text-slate-400 text-center py-6">检查中…</p>
        ) : collectUser ? (
          <div className="flex items-center gap-3 py-2">
            <Avatar face={collectUser.face} name={collectUser.name} />
            <div className="flex-1 min-w-0">
              <p className="text-sm font-semibold text-slate-800 truncate">{collectUser.name || `UID ${collectUser.mid}`}</p>
              <p className="text-xs text-slate-400 truncate">
                UID {collectUser.mid} · {collectUser.vip_status ? '大会员' : '普通账号'} · Lv{collectUser.level || 0}
              </p>
            </div>
            <button onClick={handleCollectLogout}
                    className="flex items-center gap-1.5 px-3.5 py-1.5 text-sm font-medium text-rose-600
                               border border-rose-200 hover:bg-rose-50 rounded-xl transition-colors">
              <LogOut size={14} />退出
            </button>
          </div>
        ) : (
          <div className="flex items-center gap-3 py-2">
            <p className="flex-1 text-sm text-slate-400">未登录（爬虫将以游客模式采集，412 风控风险较高）</p>
            <button onClick={() => setShowCollectLogin(true)}
                    className="flex items-center gap-1.5 px-3.5 py-1.5 text-sm font-semibold text-white
                               bg-primary-500 hover:bg-primary-600 rounded-xl transition-colors">
              <LogIn size={14} />扫码登录
            </button>
          </div>
        )}
      </section>

      {/* 采集登录弹窗（mode=collect：凭证写服务器爬虫 Cookie 文件） */}
      {showCollectLogin && (
        <BilibiliLogin mode="collect"
                       onClose={() => setShowCollectLogin(false)}
                       onLoginSuccess={handleCollectLoginSuccess} />
      )}
    </div>
  )
}
