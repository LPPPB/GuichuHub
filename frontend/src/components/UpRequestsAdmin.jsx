import { useState, useEffect, useCallback } from 'react'
import { createPortal } from 'react-dom'
import { X, ClipboardCheck, Check, XCircle, Loader2, ExternalLink, RefreshCw } from 'lucide-react'
import { api } from '../utils/api'
import { proxyImage } from '../utils/image'

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

// 访客标识只展示短前缀（UUID 不可读，也避免完整暴露）
function vidShort(vid) {
  return (vid || '').replace(/^v-/, '').slice(0, 8) || '匿名'
}

export default function UpRequestsAdmin({ onClose, embedded = false }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')
  const [notice, setNotice] = useState(null)          // { type: 'ok'|'err', text }
  const [reviewingId, setReviewingId] = useState(null) // 审核请求进行中的申请 id
  const [rejectingId, setRejectingId] = useState(null) // 展开拒绝理由输入的申请 id
  const [rejectReason, setRejectReason] = useState('')
  const [typeFilter, setTypeFilter] = useState('all')
  const [query, setQuery] = useState('')

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true)
    try {
      const res = await api.adminGetUpRequests()
      if (res.success) {
        setData(res.data || { pending: [], processed: [] })
      } else {
        setErr(res.message || '加载失败')
      }
    } catch (e) {
      setErr(e.message || '加载失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  // 审核：通过直接生效；拒绝必须填写理由（访客可见）
  const doReview = async (req, action) => {
    if (reviewingId) return
    const reason = rejectReason.trim()
    if (action === 'reject' && !reason) {
      setErr('拒绝时必须填写理由（访客可见）')
      return
    }
    setReviewingId(req.id)
    setErr('')
    setNotice(null)
    try {
      const res = await api.reviewUpRequest(req.id, action, reason)
      if (res.success) {
        const up = req.up || {}
        setNotice({
          type: 'ok',
          text: action === 'approve'
            ? `已通过 · ${up.name || `UP ${req.mid}`} ${req.request_type === 'remove' ? '停止观测，历史数据保留' : '加入观测名单'}`
            : `已拒绝 · ${up.name || `UP ${req.mid}`}`,
        })
        setRejectingId(null)
        setRejectReason('')
        await load(true)
      } else {
        setErr(res.message || '操作失败，请刷新后重试')
        if ((res.message || '').includes('已处理')) await load(true)
      }
    } catch (e) {
      setErr(e.message || '审核失败，请刷新后重试')
    } finally {
      setReviewingId(null)
    }
  }

  const matches = r => (typeFilter === 'all' || (r.request_type || 'add') === typeFilter)
    && `${r.up?.name || ''} ${r.mid} ${r.reason || ''}`.toLowerCase().includes(query.trim().toLowerCase())
  const pending = (data?.pending || []).filter(matches)
  const processed = (data?.processed || []).filter(matches)

  // Portal 到 document.body：脱离页面动画容器的 transform 包含块，fixed 定位始终相对视口
  const content = (
    <div className={embedded ? '' : 'fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4'} onClick={embedded ? undefined : onClose}>
      <div
        className={embedded ? 'bg-white rounded-2xl border border-slate-200 w-full flex flex-col overflow-hidden' : 'bg-white rounded-2xl shadow-xl w-full max-w-xl max-h-[85vh] flex flex-col overflow-hidden'}
        onClick={(e) => e.stopPropagation()}
      >
        {/* 头部 */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-100">
          <h3 className="text-lg font-bold text-slate-800 flex items-center gap-2">
            <ClipboardCheck className="text-blue-500" size={20} />
            申请审核
            {!loading && (
              <span className="text-xs font-normal px-2 py-0.5 rounded-full bg-amber-50 text-amber-600 border border-amber-200">
                待审 {pending.length}
              </span>
            )}
          </h3>
          <div className="flex items-center gap-1">
            <button
              onClick={() => { setErr(''); setNotice(null); load() }}
              disabled={loading}
              className="p-1.5 rounded-lg hover:bg-slate-100 text-slate-400 hover:text-slate-600 transition-colors disabled:opacity-50"
              aria-label="刷新列表"
              title="刷新列表"
            >
              <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
            </button>
            {!embedded && <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-slate-100 text-slate-400 transition-colors" aria-label="关闭">
              <X size={18} />
            </button>}
          </div>
        </div>

        {/* 提示条 */}
        <div className="px-5 pt-4 flex flex-wrap gap-2">
          <input aria-label="搜索申请" value={query} onChange={e => setQuery(e.target.value)} placeholder="昵称、MID 或申请原因" className="flex-1 min-w-0 rounded-lg border border-slate-200 px-3 py-2 text-sm" />
          <select aria-label="申请类型" value={typeFilter} onChange={e => setTypeFilter(e.target.value)} className="rounded-lg border border-slate-200 px-3 py-2 text-sm"><option value="all">全部类型</option><option value="add">添加观测</option><option value="remove">停止观测</option></select>
        </div>
        {notice && (
          <div className={`mx-5 mt-3 px-3 py-2 rounded-lg text-sm ${notice.type === 'ok' ? 'bg-emerald-50 text-emerald-600' : 'bg-red-50 text-red-500'}`}>
            {notice.text}
          </div>
        )}
        {err && <div className="mx-5 mt-3 px-3 py-2 rounded-lg text-sm bg-red-50 text-red-500">{err}</div>}

        {/* 内容区 */}
        <div className="flex-1 overflow-y-auto px-5 py-4">
          {loading && !data ? (
            <div className="flex items-center justify-center py-12 text-slate-400 text-sm">
              <Loader2 size={16} className="animate-spin mr-2" />加载中...
            </div>
          ) : (
            <>
              {/* 待审核 */}
              <p className="text-xs font-medium text-slate-400 mb-2">待审核（提交时快照，无需打开B站）</p>
              {pending.length === 0 && (
                <div className="text-center py-8 text-sm text-slate-400 border border-dashed border-slate-200 rounded-xl mb-4">
                  暂无待审核申请
                </div>
              )}
              {pending.length > 0 && (
                <div className="space-y-3 mb-4">
                  {pending.map((r) => {
                    const up = r.up || {}
                    return (
                      <div key={r.id} className="border border-slate-200 rounded-xl p-3.5">
                        <div className="flex items-center gap-3">
                          <img src={proxyImage(up.face)} alt={up.name} className="w-11 h-11 rounded-full bg-slate-100 object-cover flex-shrink-0" />
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2">
                              <p className="text-sm font-semibold text-slate-800 truncate">{r.request_type === 'remove' ? '停止观测' : '添加观测'} · {up.name || `UP ${r.mid}`}</p>
                              <a
                                href={`https://space.bilibili.com/${r.mid}`}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="text-slate-300 hover:text-blue-500 transition-colors flex-shrink-0"
                                title="打开UP主页核实"
                              >
                                <ExternalLink size={13} />
                              </a>
                            </div>
                            <p className="text-xs text-slate-400">
                              {fmtFans(up.fans)} · mid {r.mid}{up.sign ? ` · ${up.sign.slice(0, 30)}` : ''}
                            </p>
                          </div>
                          {/* 审核操作 */}
                          <div className="flex items-center gap-2 flex-shrink-0">
                            <button
                              onClick={() => doReview(r, 'approve')}
                              disabled={reviewingId === r.id}
                              className="flex items-center gap-1 px-3 py-1.5 text-xs font-medium bg-emerald-500 text-white rounded-lg hover:bg-emerald-600 transition-colors disabled:opacity-50"
                            >
                              {reviewingId === r.id ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />}
                              通过
                            </button>
                            {rejectingId !== r.id && (
                              <button
                                onClick={() => { setRejectingId(r.id); setRejectReason(''); setErr('') }}
                                disabled={reviewingId === r.id}
                                className="flex items-center gap-1 px-3 py-1.5 text-xs font-medium border border-red-200 text-red-500 rounded-lg hover:bg-red-50 transition-colors disabled:opacity-50"
                              >
                                <XCircle size={12} />拒绝
                              </button>
                            )}
                          </div>
                        </div>

                        {/* 申请理由 + 访客 + 时间 */}
                        {(r.reason || r.visitor_id || r.submitted_at) && (
                          <p className="mt-2 text-xs text-slate-500 break-words whitespace-pre-wrap">
                            {r.reason && <span className="text-slate-600">理由：{r.reason} · </span>}
            访客 {vidShort(r.visitor_id)} · {fmtTime(r.submitted_at)} 提交
                          </p>
                        )}

                        {/* 拒绝理由输入（必填，访客可见） */}
                        {rejectingId === r.id && (
                          <div className="mt-2.5 flex gap-2">
                            <input
                              autoFocus
                              value={rejectReason}
                              onChange={(e) => setRejectReason(e.target.value)}
                              onKeyDown={(e) => { if (e.key === 'Enter') doReview(r, 'reject') }}
                              placeholder="拒绝理由（必填，访客可见）"
                              className="flex-1 px-3 py-1.5 border border-red-200 rounded-lg text-xs focus:outline-none focus:ring-2 focus:ring-red-500/20"
                            />
                            <button
                              onClick={() => doReview(r, 'reject')}
                              disabled={reviewingId === r.id || !rejectReason.trim()}
                              className="px-3 py-1.5 bg-red-500 text-white rounded-lg text-xs font-medium hover:bg-red-600 transition-colors disabled:opacity-50 flex items-center gap-1"
                            >
                              {reviewingId === r.id ? <Loader2 size={12} className="animate-spin" /> : null}
                              确认拒绝
                            </button>
                            <button
                              onClick={() => { setRejectingId(null); setRejectReason('') }}
                              className="px-3 py-1.5 border border-slate-200 text-slate-500 rounded-lg text-xs hover:bg-slate-50 transition-colors"
                            >
                              取消
                            </button>
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              )}

              {/* 最近已处理 */}
              {processed.length > 0 && (
                <div>
                  <p className="text-xs font-medium text-slate-400 mb-2">最近已处理</p>
                  <div className="space-y-2">
                    {processed.map((r) => {
                      const up = r.up || {}
                      const meta = STATUS_META[r.status] || STATUS_META.withdrawn
                      return (
                        <div key={r.id} className="flex items-center gap-3 border border-slate-100 rounded-lg p-2.5">
                          <img src={proxyImage(up.face)} alt="" className="w-8 h-8 rounded-full bg-slate-100 object-cover flex-shrink-0" />
                          <div className="flex-1 min-w-0">
                            <p className="text-sm text-slate-700 truncate">{r.request_type === 'remove' ? '停止观测' : '添加观测'} · {up.name || `UP ${r.mid}`}</p>
                            <p className="text-xs text-slate-400 truncate">
                              {fmtTime(r.submitted_at)} 提交 · 访客 {vidShort(r.visitor_id)}
                              {r.status === 'rejected' && r.reject_reason ? ` · 理由：${r.reject_reason}` : ''}
                            </p>
                          </div>
                          <span className={`px-2 py-0.5 text-xs rounded-full border flex-shrink-0 ${meta.cls}`}>{meta.label}</span>
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}
            </>
          )}
        </div>

        {/* 底部提示 */}
        <div className="px-5 py-3 border-t border-slate-100 text-xs text-slate-400">
          添加通过后启用观测；停止通过后不再纳入后续分析，历史数据保留。拒绝理由对申请人可见。
        </div>
      </div>
    </div>
  )
  return embedded ? content : createPortal(content, document.body)
}
