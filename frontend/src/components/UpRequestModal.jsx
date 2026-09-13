import { useState, useCallback } from 'react'
import { createPortal } from 'react-dom'
import { X, UserPlus, Search, Link2, Clock, Undo2, Loader2 } from 'lucide-react'
import { api } from '../utils/api'
import { proxyImage } from '../utils/image'
import ObservationRoster from './ObservationRoster'

// 申请单状态徽章（与后端 tracked_ups.py 状态机一致）
const STATUS_META = {
  approved: { label: '已通过', cls: 'bg-emerald-50 text-emerald-600 border-emerald-200' },
  rejected: { label: '未通过', cls: 'bg-red-50 text-red-600 border-red-200' },
  superseded: { label: '已合并', cls: 'bg-slate-50 text-slate-500 border-slate-200' },
  withdrawn: { label: '已撤回', cls: 'bg-slate-50 text-slate-500 border-slate-200' },
}

function fmtFans(n) {
  if (n >= 10000) return (n / 10000).toFixed(1) + '万粉'
  return (n || 0) + ' 粉丝'
}

function fmtTime(ts) {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  const p = (x) => String(x).padStart(2, '0')
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

// 从粘贴文本解析 mid：纯数字 或 space.bilibili.com/<mid>（含 ?参数 / /dynamic 后缀）
function parseMidFromLink(text) {
  const t = (text || '').trim()
  if (/^\d+$/.test(t)) return parseInt(t, 10)
  const m = t.match(/space\.bilibili\.com\/(\d+)/)
  if (m) return parseInt(m[1], 10)
  return null
}

export default function UpRequestModal({ onClose, initialTab = 'search' }) {
  const [tab, setTab] = useState(initialTab)
  const [stopTarget, setStopTarget] = useState(null)

  // ── 搜索态 ──
  const [keyword, setKeyword] = useState('')
  const [searching, setSearching] = useState(false)
  const [results, setResults] = useState(null)      // null=未搜索，[]=无结果
  const [searchError, setSearchError] = useState('')

  // ── 申请态（选中 UP 后展开理由输入，理由选填）──
  const [applyingMid, setApplyingMid] = useState(null)
  const [reason, setReason] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [notice, setNotice] = useState(null)        // { type: 'ok'|'err', text }

  // ── 粘贴链接态 ──
  const [linkInput, setLinkInput] = useState('')

  // ── 我的申请态 ──
  const [mine, setMine] = useState(null)
  const [mineLoading, setMineLoading] = useState(false)
  const [withdrawId, setWithdrawId] = useState(null)

  const setErr = (text) => setNotice({ type: 'err', text })

  const loadMine = useCallback(async () => {
    setMineLoading(true)
    try {
      const res = await api.getMyUpRequests()
      if (res.success) setMine(res.data || { pending: [], processed: [] })
      else setErr(res.message || '申请加载失败')
    } catch (e) {
      setErr(e.message || '申请加载失败')
    } finally {
      setMineLoading(false)
    }
  }, [])

  const switchTab = (t) => {
    setTab(t)
    setStopTarget(null)
    setReason('')
    setNotice(null)
    if (t === 'mine' && !mine) loadMine()
  }

  const doSearch = async () => {
    const kw = keyword.trim()
    if (!kw || searching) return
    setSearching(true)
    setSearchError('')
    setResults(null)
    setNotice(null)
    try {
      const res = await api.searchUps(kw)
      if (res.success) {
        setResults(res.data || [])
        if (!res.data?.length) setSearchError('没有找到相关UP主，可以试试粘贴主页链接')
      } else {
        setSearchError(res.message || '搜索暂不可用，请粘贴UP主页链接申请')
      }
    } finally {
      setSearching(false)
    }
  }

  // 提交申请（mid 数字；reason 选填）
  const doSubmit = async (mid, requestType = 'add') => {
    if (submitting) return
    if (requestType === 'remove' && !reason.trim()) { setErr('请填写停止观测的原因'); return }
    setSubmitting(true)
    setNotice(null)
    try {
      const res = await api.submitUpRequest(mid, reason.trim(), requestType)
      if (res.success) {
        setNotice({ type: 'ok', text: `已提交申请（UP mid=${mid}），等待站长审核` })
        setApplyingMid(null)
        setStopTarget(null)
        setReason('')
        setResults((prev) => (prev ? prev.filter((u) => u.mid !== mid) : prev))
        loadMine()
      } else {
        setErr(res.message || '提交失败，请稍后再试')
      }
    } catch (e) {
      setErr(e.message || '提交失败，请稍后重试')
    } finally {
      setSubmitting(false)
    }
  }

  // 粘贴链接提交：解析失败就地提示，不弹后端
  const doSubmitLink = async () => {
    const mid = parseMidFromLink(linkInput)
    if (!mid) {
      setErr('链接格式不对：请粘贴 UP 主页链接（space.bilibili.com/数字）或直接输入 mid 数字')
      return
    }
    await doSubmit(mid)
    setLinkInput('')
  }

  const doWithdraw = async (id) => {
    if (withdrawId) return
    setWithdrawId(id)
    try {
      const res = await api.withdrawUpRequest(id)
      if (!res.success) setErr(res.message || '撤回失败')
      loadMine()
    } finally {
      setWithdrawId(null)
    }
  }

  const pending = mine?.pending || []
  const processed = mine?.processed || []

  // Portal 到 document.body：脱离页面动画容器的 transform 包含块，fixed 定位始终相对视口
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div
        className="bg-white rounded-2xl shadow-xl w-full max-w-lg h-[760px] max-h-[85vh] flex flex-col overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex flex-shrink-0 items-center justify-between px-5 py-4 border-b border-slate-100">
          <h3 className="text-lg font-bold text-slate-800 flex items-center gap-2">
            <UserPlus className="text-primary-500" size={20} />申请观测
          </h3>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-slate-100 text-slate-400 transition-colors" aria-label="关闭">
            <X size={18} />
          </button>
        </div>

        {/* Tabs */}
        <div className="flex flex-shrink-0 border-b border-slate-100">
          <button
            onClick={() => switchTab('search')}
            className={`flex-1 px-4 py-2.5 text-sm font-medium transition-colors ${tab === 'search' ? 'text-blue-600 border-b-2 border-blue-500' : 'text-slate-500 hover:text-slate-700'}`}
          >
            <Search size={14} className="inline mr-1.5" />添加观测
          </button>
          <button onClick={() => switchTab('roster')} className={`flex-1 px-3 py-2.5 text-sm ${tab === 'roster' ? 'text-primary-600 border-b-2 border-primary-500' : 'text-slate-500'}`}>当前名单</button>
          <button
            onClick={() => switchTab('mine')}
            className={`flex-1 px-4 py-2.5 text-sm font-medium transition-colors ${tab === 'mine' ? 'text-blue-600 border-b-2 border-blue-500' : 'text-slate-500 hover:text-slate-700'}`}
          >
            <Clock size={14} className="inline mr-1.5" />我的申请
            {pending.length > 0 && <span className="ml-1.5 text-xs bg-amber-100 text-amber-600 px-1.5 py-0.5 rounded-full">{pending.length}</span>}
          </button>
        </div>

        {/* 通知条 */}
        {notice && (
          <div className={`mx-5 mt-3 px-3 py-2 rounded-lg text-sm ${notice.type === 'ok' ? 'bg-emerald-50 text-emerald-600' : 'bg-red-50 text-red-600'}`}>
            {notice.text}
          </div>
        )}

        {/* Body */}
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          {tab === 'roster' && <>
            {stopTarget && <div className="mb-4 rounded-xl border border-amber-200 bg-amber-50 p-3 space-y-2">
              <p className="text-sm font-medium">申请停止观测：{stopTarget.name || stopTarget.mid}</p>
              <p className="text-xs text-slate-600">审核通过后停止后续观测，保留历史数据。</p>
              <textarea aria-label="停止观测原因" maxLength={200} value={reason} onChange={e => setReason(e.target.value)} placeholder="请说明原因（必填，最多200字）" className="w-full rounded-lg border border-slate-200 p-2 text-sm" />
              <div className="flex gap-3"><button disabled={submitting || !reason.trim()} onClick={() => doSubmit(stopTarget.mid, 'remove')} className="rounded-lg bg-primary-500 text-white px-3 py-2 text-sm disabled:opacity-50">{submitting ? '提交中…' : '提交停止申请'}</button><button disabled={submitting} onClick={() => setStopTarget(null)} className="text-sm text-slate-600">取消</button></div>
            </div>}
            <ObservationRoster onRequestStop={up => { setStopTarget(up); setReason(''); setNotice(null) }} />
          </>}
          {tab === 'search' && (
            <div className="space-y-4">
              {/* 搜索框 */}
              <div className="flex gap-2">
                <input
                  value={keyword}
                  onChange={(e) => setKeyword(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && doSearch()}
                  placeholder="输入UP主昵称搜索"
                  className="flex-1 px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400"
                />
                <button
                  onClick={doSearch}
                  disabled={searching || !keyword.trim()}
                  className="px-4 py-2 bg-blue-500 text-white rounded-lg text-sm font-medium hover:bg-blue-600 transition-colors disabled:opacity-50 flex items-center gap-1.5"
                >
                  {searching ? <Loader2 size={14} className="animate-spin" /> : <Search size={14} />}
                  {searching ? '搜索中' : '搜索'}
                </button>
              </div>

              {/* 搜索结果 */}
              {searchError && <p className="text-sm text-amber-600 bg-amber-50 px-3 py-2 rounded-lg">{searchError}</p>}
              {results && results.length > 0 && (
                <div className="space-y-2">
                  {results.map((u) => (
                    <div key={u.mid} className="border border-slate-100 rounded-lg p-3 hover:border-blue-200 transition-colors">
                      <div className="flex items-center gap-3">
                        <img src={proxyImage(u.face)} alt={u.name} className="w-10 h-10 rounded-full bg-slate-100 object-cover flex-shrink-0"
                          onError={(e) => { e.currentTarget.style.visibility = 'hidden' }} />
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-medium text-slate-800 truncate">{u.name}</p>
                          <p className="text-xs text-slate-400">
                            {fmtFans(u.fans)} · mid {u.mid}{u.sign ? ` · ${u.sign.slice(0, 24)}` : ''}
                          </p>
                        </div>
                        {applyingMid === u.mid ? (
                          <button onClick={() => { setApplyingMid(null); setReason('') }}
                            className="text-xs text-slate-400 hover:text-slate-600 px-2 py-1">取消</button>
                        ) : (
                          <button
                            onClick={() => { setApplyingMid(u.mid); setNotice(null) }}
                            className="px-3 py-1.5 text-xs font-medium bg-blue-50 text-blue-600 rounded-lg hover:bg-blue-100 transition-colors flex-shrink-0"
                          >
                            申请追踪
                          </button>
                        )}
                      </div>
                      {/* 展开的申请理由（选填） */}
                      {applyingMid === u.mid && (
                        <div className="mt-3 flex gap-2">
                          <input
                            value={reason}
                            onChange={(e) => setReason(e.target.value)}
                            placeholder="申请理由（选填，帮助站长了解）"
                            className="flex-1 px-3 py-1.5 border border-slate-200 rounded-lg text-xs focus:outline-none focus:ring-2 focus:ring-blue-500/20"
                          />
                          <button
                            onClick={() => doSubmit(u.mid)}
                            disabled={submitting}
                            className="px-3 py-1.5 bg-blue-500 text-white rounded-lg text-xs font-medium hover:bg-blue-600 transition-colors disabled:opacity-50"
                          >
                            {submitting ? '提交中' : '提交'}
                          </button>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}

              {/* 粘贴链接（搜索不可用的降级入口） */}
              <div className="border-t border-slate-100 pt-4">
                <p className="text-xs text-slate-400 mb-2 flex items-center gap-1">
                  <Link2 size={12} />搜不到？粘贴 UP 主页链接直接申请（每日最多 3 个）
                </p>
                <div className="flex gap-2">
                  <input
                    value={linkInput}
                    onChange={(e) => setLinkInput(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && doSubmitLink()}
                    placeholder="https://space.bilibili.com/12345 或直接输入 mid"
                    className="flex-1 px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400"
                  />
                  <button
                    onClick={doSubmitLink}
                    disabled={submitting}
                    className="px-4 py-2 border border-slate-200 text-slate-600 rounded-lg text-sm font-medium hover:bg-slate-50 transition-colors disabled:opacity-50"
                  >
                    提交
                  </button>
                </div>
              </div>
            </div>
          )}

          {tab === 'mine' && (
            <div className="space-y-4">
              {mineLoading && !mine && (
                <div className="flex items-center justify-center py-10 text-slate-400 text-sm">
                  <Loader2 size={16} className="animate-spin mr-2" />加载中...
                </div>
              )}
              {mine && pending.length === 0 && processed.length === 0 && (
                <div className="text-center py-10 text-sm text-slate-400">还没有提交过申请</div>
              )}

              {/* 待审核 */}
              {pending.length > 0 && (
                <div>
                  <p className="text-xs font-medium text-slate-400 mb-2">待审核</p>
                  <div className="space-y-2">
                    {pending.map((r) => (
                      <div key={r.id} className="flex items-center gap-3 border border-amber-100 bg-amber-50/50 rounded-lg p-3">
                        <img src={proxyImage(r.up?.face)} alt="" className="w-9 h-9 rounded-full bg-slate-100 object-cover flex-shrink-0" />
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-medium text-slate-800 truncate">{r.request_type === 'remove' ? '停止观测' : '添加观测'} · {r.up?.name || `UP ${r.mid}`}</p>
                          <p className="text-xs text-slate-400">{fmtTime(r.submitted_at)} 提交{r.reason ? ` · ${r.reason}` : ''}</p>
                        </div>
                        <button
                          onClick={() => doWithdraw(r.id)}
                          disabled={withdrawId === r.id}
                          className="px-2.5 py-1.5 text-xs text-slate-500 hover:text-red-500 border border-slate-200 rounded-lg hover:border-red-200 transition-colors disabled:opacity-50 flex items-center gap-1 flex-shrink-0"
                        >
                          <Undo2 size={12} />{withdrawId === r.id ? '撤回中' : '撤回'}
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* 已处理（含拒绝理由） */}
              {processed.length > 0 && (
                <div>
                  <p className="text-xs font-medium text-slate-400 mb-2">已处理</p>
                  <div className="space-y-2">
                    {processed.map((r) => {
                      const meta = STATUS_META[r.status] || STATUS_META.withdrawn
                      return (
                        <div key={r.id} className="border border-slate-100 rounded-lg p-3">
                          <div className="flex items-center gap-3">
                            <img src={proxyImage(r.up?.face)} alt="" className="w-9 h-9 rounded-full bg-slate-100 object-cover flex-shrink-0" />
                            <div className="flex-1 min-w-0">
                              <p className="text-sm font-medium text-slate-800 truncate">{r.request_type === 'remove' ? '停止观测' : '添加观测'} · {r.up?.name || `UP ${r.mid}`}</p>
                              <p className="text-xs text-slate-400">{fmtTime(r.submitted_at)} 提交 · {fmtTime(r.reviewed_at)} 审核</p>
                            </div>
                            <span className={`px-2 py-0.5 text-xs rounded-full border flex-shrink-0 ${meta.cls}`}>{meta.label}</span>
                          </div>
                          {r.status === 'rejected' && r.reject_reason && (
                            <p className="mt-2 text-xs text-red-500 bg-red-50 rounded-lg px-3 py-2">拒绝理由：{r.reject_reason}</p>
                          )}
                          {r.status === 'approved' && (
                            <p className="mt-2 text-xs text-emerald-600 bg-emerald-50 rounded-lg px-3 py-2">{r.request_type === 'remove' ? '停止观测申请已通过，历史数据保留' : '添加观测申请已通过'}</p>
                          )}
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer 提示 */}
        <div className="flex-shrink-0 px-5 py-3 border-t border-slate-100 text-xs text-slate-400">
          两类申请合计每日最多 3 次；待审核时可撤回。申请记录保存在当前浏览器身份下。
        </div>
      </div>
    </div>,
    document.body
  )
}
