import { useState, useEffect, useMemo, useCallback, useRef } from 'react'
import {
  Search, CheckSquare, Square, Users, ArrowRight,
  ExternalLink, Download, Upload, AlertTriangle, X, CheckCircle,
} from 'lucide-react'
import { api, getWriteToken } from '../utils/api'
import { proxyImage } from '../utils/image'

const formatNumber = (n) => (n >= 10000 ? (n / 10000).toFixed(1) + '万' : n)

// 本地时间格式化为 YYYYMMDD_HHMMSS（与后端文件名格式一致）
const formatLocalTs = () => {
  const d = new Date()
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}_${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`
}

// 构造错误详情（供用户一键复制发送给开发者诊断）
const buildErrorDetail = (operation, err) => {
  const lines = [
    `【${operation}失败】`,
    `时间：${new Date().toLocaleString('zh-CN')}`,
  ]
  if (err && err.status) lines.push(`HTTP状态：${err.status}`)
  lines.push(`错误：${(err && err.message) || (operation + '失败')}`)
  return lines.join('\n')
}

export default function UpTrendsSetup({ onComplete, onCancel, localOnly = false }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)         // 仅用于 loadList 失败的全屏 error
  const [notice, setNotice] = useState(null)       // 操作反馈: { type: 'success'|'error', text, detail }
  const [copied, setCopied] = useState(false)      // 复制错误按钮的反馈状态
  const [saving, setSaving] = useState(false)
  const [selected, setSelected] = useState(new Set())
  const [searchQuery, setSearchQuery] = useState('')

  // Fetch the mutual follow list on mount
  const loadList = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await (localOnly ? api.getObservationManagement() : api.upTrendsList())
      if (res.success && res.data) {
        setData(res.data)
        // Pre-select based on saved state: unchanged read enabled, added default true
        const initialSelected = new Set()
        ;(res.data.unchanged || []).forEach((up) => {
          if (up.enabled !== false) initialSelected.add(up.mid)
        })
        ;(res.data.added || []).forEach((up) => {
          initialSelected.add(up.mid)
        })
        setSelected(initialSelected)
      } else {
        setError(res.message || '获取名单失败')
      }
    } catch (e) {
      setError(e.message || '网络错误')
    }
    setLoading(false)
  }, [localOnly])

  useEffect(() => {
    loadList()
  }, [loadList])

  // Build a flat list with status tags
  const fullList = useMemo(() => {
    if (!data) return []
    const added = (data.added || []).map((up) => ({ ...up, _status: 'added' }))
    const removed = (data.removed || []).map((up) => ({ ...up, _status: 'removed' }))
    const unchanged = (data.unchanged || []).map((up) => ({ ...up, _status: 'unchanged' }))
    return [...added, ...unchanged, ...removed]
  }, [data])

  // Filter by search query
  const filteredList = useMemo(() => {
    if (!searchQuery.trim()) return fullList
    const q = searchQuery.trim().toLowerCase()
    return fullList.filter((up) => `${up.name || ''} ${up.mid}`.toLowerCase().includes(q))
  }, [fullList, searchQuery])

  // All non-removed UP主
  const nonRemovedList = useMemo(() => fullList.filter((up) => up._status !== 'removed'), [fullList])

  // Toggle a single UP主
  const toggle = (mid) => {
    // Removed UP主 are uncheckable
    const up = fullList.find((u) => u.mid === mid)
    if (up && up._status === 'removed') return
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(mid)) {
        next.delete(mid)
      } else {
        next.add(mid)
      }
      return next
    })
  }

  // Select all non-removed
  const selectAll = () => {
    setSelected(new Set(nonRemovedList.map((u) => u.mid)))
  }

  // Deselect all
  const deselectAll = () => {
    setSelected(new Set())
  }

  // Invert selection (only for non-removed)
  const invertSelection = () => {
    setSelected((prev) => {
      const next = new Set()
      nonRemovedList.forEach((up) => {
        if (!prev.has(up.mid)) {
          next.add(up.mid)
        }
      })
      return next
    })
  }

  // Save the list
  const handleSave = async () => {
    if (saving) return
    setSaving(true)
    setNotice(null)
    setError(null)  // 清空旧的 loadList 错误，避免残留显示
    try {
      // Build merged list: unchanged + added, with enabled based on selection
      const ups = [...(data.added || []), ...(data.unchanged || [])].map((up) => ({
        mid: up.mid,
        name: up.name,
        face: up.face,
        follower_count: up.follower_count,
        enabled: selected.has(up.mid),
      }))
      const res = await api.upTrendsSaveList(ups)
      if (res.success) {
        onComplete && onComplete()
      } else {
        setNotice({ type: 'error', text: res.message || '保存失败' })
      }
    } catch (e) {
      setNotice({ type: 'error', text: e.message || '保存失败' })
    } finally {
      setSaving(false)
    }
  }

  // --- 导入/导出 ---
  const fileInputRef = useRef(null)
  const [importing, setImporting] = useState(false)
  const [exporting, setExporting] = useState(false)

  // 导出：POST 当前页面看到的名单（排除已取关），用 Blob 触发下载。
  // 后端文件名格式：关注名单_{人数}人_{时间戳}.json，从 Content-Disposition 提取。
  // 不再用 window.open —— POST 页面当前名单可确保导出与用户所见一致。
  const handleExport = async () => {
    if (exporting) return
    setExporting(true)
    setNotice(null)
    setError(null)  // 清空旧的 loadList 错误，避免残留显示
    try {
      const ups = fullList
        .filter((up) => up._status !== 'removed')
        .map((up) => ({
          mid: up.mid,
          name: up.name,
          face: up.face,
          follower_count: up.follower_count,
          enabled: selected.has(up.mid),
        }))
      const res = await fetch(api.upTrendsExportList(), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          // 写操作口令：与 api.js 共用 localStorage 缓存（未设置时提示用户先做一次写操作）
          ...(getWriteToken() ? { 'X-Write-Token': getWriteToken() } : {}),
        },
        body: JSON.stringify({ ups }),
      })
      if (res.status === 401) {
        throw new Error('写操作口令缺失或错误：请先在页面进行任意写操作（如收藏/刷新）输入口令后再导出')
      }
      if (!res.ok) {
        let msg = '导出失败'
        try { const err = await res.json(); msg = err.message || msg } catch {}
        const e = new Error(msg)
        e.status = res.status  // 保留 HTTP 状态码供错误详情使用
        throw e
      }
      const blob = await res.blob()
      // 从 Content-Disposition 提取文件名（后端按 RFC 5987 编码中文）
      const cd = res.headers.get('Content-Disposition') || ''
      // fallback 用 YYYYMMDD_HHMMSS 格式，与后端一致（不用 Date.now 毫秒时间戳）
      let filename = `关注名单_${ups.length}人_${formatLocalTs()}.json`
      const mStar = cd.match(/filename\*=UTF-8''([^;]+)/i)
      const mPlain = cd.match(/filename="?([^";]+)"?/i)
      if (mStar) {
        try { filename = decodeURIComponent(mStar[1]) } catch {}
      } else if (mPlain) {
        filename = mPlain[1]
      }
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
      setNotice({ type: 'success', text: `导出成功：${filename}（共 ${ups.length} 人）` })
    } catch (e) {
      setNotice({
        type: 'error',
        text: e.message || '导出失败',
        detail: buildErrorDetail('导出', e),
      })
    } finally {
      setExporting(false)
    }
  }

  // 导入：点击后触发隐藏 file input
  const handleImportClick = () => {
    fileInputRef.current?.click()
  }

  // 读取文件并调用导入 API
  const handleImportFile = async (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    setImporting(true)
    setNotice(null)
    setError(null)  // 清空旧的 loadList 错误，避免残留显示
    try {
      const text = await file.text()
      const parsed = JSON.parse(text)
      // 兼容两种格式：带 format 头的导出文件 / 纯 ups 数组
      const ups = Array.isArray(parsed) ? parsed : (parsed.ups || parsed)
      if (!Array.isArray(ups) || ups.length === 0) {
        throw new Error('文件格式错误：未找到 ups 列表')
      }
      const res = await api.upTrendsImportList(ups)
      if (!res.success) {
        throw new Error(res.message || '导入失败')
      }
      // 导入成功后重新加载列表，让用户看到导入的UP主
      await loadList()
      // 不再用原生 alert（阻塞 UI），改为 notice success banner
      setNotice({ type: 'success', text: res.message || '导入完成' })
    } catch (err) {
      setNotice({
        type: 'error',
        text: err.message || '导入失败：文件解析错误',
        detail: buildErrorDetail('导入', err),
      })
    } finally {
      setImporting(false)
      e.target.value = ''  // 重置以便重复导入同一文件
    }
  }

  // --- Loading state ---
  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="w-8 h-8 border-4 border-primary-500 border-t-transparent rounded-full animate-spin" />
        <span className="ml-3 text-slate-500">正在加载{localOnly ? '观测名单' : '互粉UP主列表'}...</span>
      </div>
    )
  }

  // --- Error state ---
  if (error && !data) {
    return (
      <div className="flex flex-col items-center justify-center py-20">
        <Users className="text-slate-300 mb-4" size={48} />
        <p className="text-slate-500 mb-2">{error}</p>
        <button
          onClick={loadList}
          className="px-4 py-2 bg-primary-500 text-white rounded-lg hover:bg-primary-600 transition-colors mt-4"
        >
          重新尝试
        </button>
      </div>
    )
  }

  const totalCount = fullList.length
  const selectedCount = selected.size
  // banner 反馈项：notice 优先（操作反馈），否则降级到 error（loadList 刷新失败）
  const bannerItem = notice || (error ? { type: 'error', text: error } : null)
  const closeBanner = () => { setNotice(null); setError(null) }

  // 一键复制错误详情到剪贴板（用户可粘贴发送给开发者诊断）
  const copyErrorDetail = async () => {
    if (!bannerItem || !bannerItem.detail) return
    let ok = false
    try {
      await navigator.clipboard.writeText(bannerItem.detail)
      ok = true
    } catch {
      // clipboard API 不可用时 fallback 到 execCommand
      try {
        const ta = document.createElement('textarea')
        ta.value = bannerItem.detail
        ta.style.position = 'fixed'
        ta.style.opacity = '0'
        document.body.appendChild(ta)
        ta.select()
        ok = document.execCommand('copy')
        document.body.removeChild(ta)
      } catch {}
    }
    if (ok) {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }

  return (
    <div className="flex flex-col h-full">
      {/* Top bar: title + counts */}
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-2xl font-bold text-slate-800 flex items-center gap-2">
          <Users className="text-primary-500" /> {localOnly ? '配置观测名单' : '配置关注名单'}
        </h2>
        <div className="flex items-center gap-3 text-sm text-slate-500">
          <span>{localOnly ? '名单总数' : '互粉总数'}: <strong className="text-slate-700">{totalCount}</strong></span>
          <span className="text-slate-300">|</span>
          <span>已选: <strong className="text-blue-600">{selectedCount}</strong></span>
        </div>
      </div>

      {/* Action buttons row */}
      <div className="flex items-center gap-2 mb-4">
        <button
          onClick={selectAll}
          className="px-3 py-1.5 text-sm font-medium bg-white border border-slate-200 text-slate-600 rounded-lg hover:bg-slate-50 transition-colors"
        >
          全选
        </button>
        <button
          onClick={deselectAll}
          className="px-3 py-1.5 text-sm font-medium bg-white border border-slate-200 text-slate-600 rounded-lg hover:bg-slate-50 transition-colors"
        >
          全不选
        </button>
        <button
          onClick={invertSelection}
          className="px-3 py-1.5 text-sm font-medium bg-white border border-slate-200 text-slate-600 rounded-lg hover:bg-slate-50 transition-colors"
        >
          反选
        </button>

        {/* 分隔线 */}
        <div className="w-px h-6 bg-slate-200 mx-1"></div>

        {/* 导入/导出按钮 */}
        <button
          onClick={handleExport}
          disabled={exporting || nonRemovedList.length === 0}
          className="px-3 py-1.5 text-sm font-medium bg-white border border-slate-200 text-slate-600 rounded-lg hover:bg-slate-50 transition-colors flex items-center gap-1.5 disabled:opacity-50"
          title="导出当前关注名单为JSON文件（备份/迁移/分享）"
        >
          <Download size={14} />
          {exporting ? '导出中...' : '导出'}
        </button>
        <button
          onClick={handleImportClick}
          disabled={importing}
          className="px-3 py-1.5 text-sm font-medium bg-white border border-slate-200 text-slate-600 rounded-lg hover:bg-slate-50 transition-colors flex items-center gap-1.5 disabled:opacity-50"
          title="从JSON文件导入关注名单（按UID去重合并）"
        >
          <Upload size={14} />
          {importing ? '导入中...' : '导入'}
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept=".json,application/json"
          onChange={handleImportFile}
          className="hidden"
        />

        {/* Search input */}
        <div className="relative ml-auto">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={16} />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="搜索UP主名称..."
            className="pl-9 pr-4 py-1.5 text-sm bg-white border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent w-56 transition-colors"
          />
        </div>
      </div>

      {/* Notice/Error banner — 操作反馈（成功绿色/失败红色），紧贴 action row，不被滚动列表挡住 */}
      {bannerItem && data && (
        <div className={`mb-3 flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm border ${
          bannerItem.type === 'success'
            ? 'bg-green-50 border-green-200 text-green-700'
            : 'bg-red-50 border-red-200 text-red-600'
        }`}>
          {bannerItem.type === 'success'
            ? <CheckCircle size={16} className="flex-shrink-0" />
            : <AlertTriangle size={16} className="flex-shrink-0" />}
          <span className="flex-1 break-words">{bannerItem.text}</span>
          {bannerItem.type === 'error' && bannerItem.detail && (
            <button
              onClick={copyErrorDetail}
              className="flex-shrink-0 px-2 py-0.5 text-xs rounded border border-red-300 hover:bg-red-100 transition-colors whitespace-nowrap"
              title="复制错误信息发送给开发者"
            >
              {copied ? '已复制✓' : '复制错误'}
            </button>
          )}
          <button
            onClick={closeBanner}
            className={`p-0.5 rounded transition-colors flex-shrink-0 ${
              bannerItem.type === 'success' ? 'hover:bg-green-100' : 'hover:bg-red-100'
            }`}
            title="关闭"
          >
            <X size={14} />
          </button>
        </div>
      )}

      {/* Scrollable list */}
      <div className="flex-1 overflow-y-auto bg-white rounded-xl border border-slate-200">
        {filteredList.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-slate-400">
            <Users size={40} className="mb-3 opacity-50" />
            <p>{searchQuery.trim() ? '没有匹配的UP主' : '暂无UP主数据'}</p>
          </div>
        ) : (
          <div className="divide-y divide-slate-100">
            {filteredList.map((up) => {
              const isAdded = up._status === 'added'
              const isRemoved = up._status === 'removed'
              const isSelected = selected.has(up.mid)
              const disabled = isRemoved

              return (
                <div
                  key={up.mid}
                  className={`relative overflow-hidden flex items-center gap-3 px-4 py-3 transition-colors ${
                    isRemoved
                      ? 'bg-red-50/50'
                      : isAdded
                        ? 'bg-green-50/30'
                        : 'hover:bg-slate-50'
                  }`}
                >
                  {/* 左侧小蓝条：选中/新增态 → B 站蓝 浅→深 纵向渐变色（替代原单色显扁平） */}
                  {(isSelected || isAdded) && (
                    <span className="absolute left-0 top-0 bottom-0 w-[3px] shrink-0
                                     bg-gradient-to-b from-bili-default to-bili-dark" />
                  )}

                  {/* Checkbox — 小细节改 B 站蓝色（品牌色 text-bili-default / hover 更亮 bili-dark）*/}
                  <button
                    onClick={() => toggle(up.mid)}
                    disabled={disabled}
                    className={`flex-shrink-0 p-0.5 rounded transition-colors ${
                      disabled
                        ? 'text-slate-300 cursor-not-allowed'
                        : isSelected
                          ? 'text-bili-default hover:text-bili-dark'
                          : 'text-slate-300 hover:text-bili-default'
                    }`}
                  >
                    {isSelected ? <CheckSquare size={20} /> : <Square size={20} />}
                  </button>

                  {/* Avatar */}
                  <img
                    src={proxyImage(up.face)}
                    alt={up.name}
                    className="w-10 h-10 rounded-full object-cover bg-slate-100 flex-shrink-0"
                    onError={(e) => {
                      e.target.style.display = 'none'
                    }}
                  />

                  {/* Name + follower count */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className={`text-sm font-medium truncate ${isRemoved ? 'text-slate-400 line-through' : 'text-slate-700'}`}>
                        {up.name}
                      </span>
                    </div>
                    <div className="text-xs text-slate-400 mt-0.5">
                      {up.follower_count ? `粉丝 ${formatNumber(up.follower_count)}` : `UID: ${up.mid}`}
                    </div>
                  </div>

                  {/* Status badges + link */}
                  <div className="flex items-center gap-1.5 flex-shrink-0">
                    {isAdded && (
                      <span className="text-xs px-1.5 py-0.5 rounded font-medium bg-green-100 text-green-700 border border-green-200">
                        🆕 新增
                      </span>
                    )}
                    {isRemoved && (
                      <span className="text-xs px-1.5 py-0.5 rounded font-medium bg-red-100 text-red-600 border border-red-200">
                        ⚠️ 已取关
                      </span>
                    )}
                    <a
                      href={`https://space.bilibili.com/${up.mid}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      onClick={(e) => e.stopPropagation()}
                      className="p-1.5 text-slate-400 hover:text-primary-500 hover:bg-primary-50 rounded-lg transition-colors"
                      title="打开UP主空间"
                    >
                      <ExternalLink size={14} />
                    </a>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* Bottom bar */}
      <div className="flex items-center justify-end gap-3 mt-4 pt-4 border-t border-slate-200">
        <button
          onClick={onCancel}
          className="px-5 py-2.5 text-sm font-medium bg-white border border-slate-200 text-slate-600 rounded-lg hover:bg-slate-50 transition-colors"
        >
          取消
        </button>
        <button
          onClick={handleSave}
          disabled={saving || selectedCount === 0}
          className="px-5 py-2.5 text-sm font-medium bg-primary-500 text-white rounded-lg hover:bg-primary-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-2"
        >
          {saving ? (
            <>
              <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
              保存中...
            </>
          ) : (
            <>
              保存并开始分析
              <ArrowRight size={16} />
            </>
          )}
        </button>
      </div>
    </div>
  )
}
