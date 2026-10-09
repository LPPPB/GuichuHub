import { useState, useMemo, useEffect, useRef, useCallback } from 'react'
import { createPortal } from 'react-dom'
import { Users, Sparkles, Trophy, Calendar, ExternalLink, RefreshCw } from 'lucide-react'
import { api } from '../utils/api'
import EChart from './EChart'

// ── 共享工具（模块级，各卡片与外部组件复用）───────────────────────
export function formatDate(ts) {
  if (!ts) return '--'
  const d = new Date(ts * 1000)
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${m}-${day}`
}

export function formatNumber(n) {
  if (n == null || isNaN(n)) return '0'
  if (n >= 100000000) return (n / 100000000).toFixed(1) + '亿'
  if (n >= 10000) return (n / 10000).toFixed(1) + '万'
  return n.toLocaleString('zh-CN')
}

// 格式化变化值（支持负数，用绝对值判断单位，自动带正负号）
export function formatChange(n) {
  if (n == null || isNaN(n)) return '0'
  const sign = n > 0 ? '+' : n < 0 ? '-' : ''
  const abs = Math.abs(n)
  if (abs >= 100000000) return sign + (abs / 100000000).toFixed(1) + '亿'
  if (abs >= 10000) return sign + (abs / 10000).toFixed(1) + '万'
  return sign + abs.toLocaleString('zh-CN')
}

// ── 播放量排行变化：对比最新批与上一批，算出每个 UP 的变化值/变化幅度名次/排名状态 ──
// 纯函数（从 useBatchData 抽出便于单测）：输入两批分析数据，返回按 |播放量变化| 降序
// 排序后的数组，每项含 changeRank（连续 1-N，Y 轴显示）、currentRank（播放量名次，供
// tooltip 排名变化对比）、viewsChange/viewsChangePct、rankState（same/new/n/a）、change（↑↓→）。
export function computeRankingData(latest, previous) {
  const latestRanking = latest?.analysis?.play_ranking || latest?.analysis?.active_ranking || []
  const prevRanking = previous?.analysis?.play_ranking || previous?.analysis?.active_ranking || []
  // 排名对比口径：两侧必须同为播放量排行（play_ranking）才计算箭头。
  // 早期历史批次只有 active_ranking（活跃度位次），与播放量位次混算会让
  // "↑/↓"不反映播放量排名变化（口径错位）。播放量差值不受此限制——
  // total_recent_views 两侧同源（up_obs.views_30d），跨源对比仍成立。
  const latestRankSrc = latest?.analysis?.play_ranking?.length ? 'play' : 'active'
  const prevRankSrc = previous?.analysis?.play_ranking?.length ? 'play' : 'active'
  const rankComparable = latestRankSrc === 'play' && prevRankSrc === 'play'
  const prevMap = new Map()
  if (rankComparable) {
    prevRanking.forEach((up, i) => prevMap.set(up.mid, i + 1))
  }
  const prevViewsMap = new Map()
  prevRanking.forEach((up) => prevViewsMap.set(up.mid, up.total_recent_views || 0))

  const items = latestRanking.slice(0, 10).map((up, i) => {
    const currentRank = i + 1
    const prevRank = prevMap.get(up.mid)
    const prevViews = prevViewsMap.get(up.mid)
    const currentViews = up.total_recent_views || 0
    let change = null
    let arrow = null
    let viewsChange = null
    let viewsChangePct = null
    // 播放量差值独立于排名源：total_recent_views 两侧同口径，上一批有播放数据即可对比
    if (prevViews !== undefined) {
      viewsChange = currentViews - prevViews
      viewsChangePct = prevViews > 0 ? (viewsChange / prevViews) * 100 : null
    }
    // 排名状态：'same'=可比且在榜 / 'new'=可比但上一批不在榜 / 'n/a'=排名源不同不可比
    let rankState = 'n/a'
    if (rankComparable) {
      if (prevRank !== undefined) {
        rankState = 'same'
        const diff = prevRank - currentRank
        if (diff > 0) arrow = '↑'
        else if (diff < 0) arrow = '↓'
        else arrow = '→'
        change = { arrow, diff: Math.abs(diff), isNew: false }
      } else {
        rankState = 'new'
        change = { arrow: null, diff: 0, isNew: true }
      }
    }
    // noPrevData: 上一批榜单无此 UP 的对比数据（prevViews 缺失）。rankComparable=true 时
    // 即"真新上榜"（rankState=new）；rankComparable=false 时为"数据源切换导致丢失对比基准"
    // ——后者是排查重点，诊断日志会单独列出这些 UP。
    return { ...up, currentRank, prevRank, change, rankState, prevViews, viewsChange, viewsChangePct, noPrevData: prevViews === undefined }
  })

  const maxAbsChange = Math.max(...items.map(u => Math.abs(u.viewsChange || 0)), 1)
  // 排序：按播放量变化绝对值降序（变化幅度大的在上），涨跌双向对称——与正负对称柱
  // 的视觉一致（最长的柱在最上面）。viewsChange 为 null（新上榜）或 0（无变化）排最后；
  // 相同幅度保持原顺序（最新批播放量降序，V8 sort 稳定）。
  items.sort((a, b) => Math.abs(b.viewsChange || 0) - Math.abs(a.viewsChange || 0))
  // changeRank = 变化幅度名次（连续 1-10），供 Y 轴标签显示，重排后连续直观。
  // currentRank 保留为"最新批播放量名次"，供 tooltip 排名变化对比——它必须与 prevRank
  // （上一批播放量名次）同口径才能算 ↑↓，不可用 changeRank 覆盖。
  return items.map((u, i) => ({ ...u, maxAbsChange, changeRank: i + 1 }))
}

// ── 共享批次数据 hook：历史批次 → 各图表的派生数据 ────────────────
// 只保留有 up_obs 数据的批次（早期批次可能无 summary/ranking，会让趋势图出现0值断点）
function useBatchData(batches) {
  const validBatches = useMemo(
    () => batches.filter(s => s.analysis?.summary && s.analysis.summary.total_ups > 0),
    [batches]
  )
  const latest = validBatches.length > 0 ? validBatches[validBatches.length - 1] : null
  const previous = validBatches.length > 1 ? validBatches[validBatches.length - 2] : null
  const singleMode = validBatches.length <= 1

  // 活跃UP主变化
  const activeData = useMemo(() => {
    return validBatches.map((s) => ({
      date: formatDate(s.created_at),
      count: s.analysis?.summary?.active_up_count || 0,
    }))
  }, [validBatches])

  // 鬼畜视频占比
  const kichuRatioData = useMemo(() => {
    return validBatches.map((s) => {
      const sum = s.analysis?.summary || {}
      const kichu = sum.kichu_video_count || 0
      const total = sum.total_videos || 1
      return {
        date: formatDate(s.created_at),
        ratio: total > 0 ? kichu / total : 0,
        kichu,
        total,
      }
    })
  }, [validBatches])
  const latestKichu = kichuRatioData.length > 0 ? kichuRatioData[kichuRatioData.length - 1] : { ratio: 0, kichu: 0, total: 0 }
  const kichuPct = (latestKichu.ratio * 100).toFixed(1)

  // 播放量排行变化（纯函数 computeRankingData，便于单测）
  const rankingData = useMemo(() => computeRankingData(latest, previous), [latest, previous])

  // 数据源切换降级诊断：仅当两批数据源不一致（非同为 play_ranking）时打 warn，方便排查
  // （两批同为 play_ranking 时，新上榜是常态，不打日志避免刷屏）
  useEffect(() => {
    if (rankingData.length === 0 || !previous) return
    const latestSrc = latest?.analysis?.play_ranking?.length ? 'play_ranking' : 'active_ranking'
    const prevSrc = previous?.analysis?.play_ranking?.length ? 'play_ranking' : 'active_ranking'
    const comparable = latestSrc === 'play_ranking' && prevSrc === 'play_ranking'
    if (comparable) return  // 同为 play_ranking → 正常，不排查
    const lost = rankingData.filter(u => u.noPrevData)
    const lostDetail = lost.map(u => `${u.name}(mid=${u.mid})`).join(', ') || '无'
    console.warn(
      `[PlayRankingChange] 批次 ${formatDate(latest?.created_at)} vs ${formatDate(previous?.created_at)} | ` +
      `数据源 latest=${latestSrc}, previous=${prevSrc} → 口径不一致，排名箭头降级 n/a | ` +
      `丢失对比数据 ${lost.length}/${rankingData.length}: ${lostDetail}`
    )
  }, [rankingData, latest, previous])

  return { validBatches, latest, previous, singleMode, activeData, kichuRatioData, latestKichu, kichuPct, rankingData }
}

// ── Chart card wrapper ───────────────────────────────────────────────
function ChartCard({ icon: Icon, iconColor, title, children, note, fullWidth, extra }) {
  return (
    <div className={`bg-white rounded-xl border border-slate-200 p-5 ${fullWidth ? 'lg:col-span-2' : ''}`}>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Icon className={iconColor} size={20} />
          <h3 className="text-base font-bold text-slate-800">{title}</h3>
        </div>
        {extra && <div>{extra}</div>}
      </div>
      {note && (
        <p className="text-xs text-amber-500 mb-2 bg-amber-50 px-3 py-1.5 rounded-lg">{note}</p>
      )}
      {children}
    </div>
  )
}

// ════════════════════════════════════════════════════════════════════
// 卡片1：发布日历热力图（含周发布量/周播放量频率折线）
// ════════════════════════════════════════════════════════════════════
export function PublishCalendarCard({ batches = [], isAdmin = false, onCalendarUpdated }) {
  const tooltipRef = useRef(null)
  const [calendarDetail, setCalendarDetail] = useState(null)
  const [heatmapMode, setHeatmapMode] = useState('count') // 'count' | 'views'
  const [calendarMap, setCalendarMap] = useState({})  // { 'YYYY-MM-DD': {count, views}, ... }
  const [calendarStatus, setCalendarStatus] = useState('loading') // loading | ready | empty | error
  const [calendarError, setCalendarError] = useState('')
  const [calendarFetchedAt, setCalendarFetchedAt] = useState(null)
  const [refreshToken, setRefreshToken] = useState(0)
  const [backfillMenuOpen, setBackfillMenuOpen] = useState(false)  // 刷新窗口选择菜单
  const [backfilling, setBackfilling] = useState(false)
  const [backfillMsg, setBackfillMsg] = useState('')               // 回填启动提示
  const [backfillOk, setBackfillOk] = useState(false)              // 提示条成功/失败语义（绿色/红色）
  const [backfillJob, setBackfillJob] = useState(null)
  const [activeJobId, setActiveJobId] = useState(null)
  const calendarAbortRef = useRef(null)
  // 当天视频列表：点击日历格子后按日期拉取（日历点击 → 视频列表）
  const [dayVideos, setDayVideos] = useState(null)          // null=未加载/加载中, [] = 空
  const [dayVideosLoading, setDayVideosLoading] = useState(false)
  const [dayVideosError, setDayVideosError] = useState(null) // 单日视频加载错误信息（区分服务端故障与"当天无数据"）
  const dayVideosAbortRef = useRef(null)

  // ── Tooltip via DOM ref (avoids re-render on hover) ────────────────
  // 悬浮窗加速跟随：内容即时更新（innerHTML），位置由 rAF 缓动追赶鼠标（lerp），快速滑动时呈滞后加速度感
  const tooltipPosRef = useRef({ x: 0, y: 0 })      // 当前渲染位置
  const tooltipTargetRef = useRef({ x: 0, y: 0 })   // 目标位置（鼠标处）
  const tooltipRafRef = useRef(null)
  const tooltipPosAppliedRef = useRef({ x: -1, y: -1 }) // 上次写入 transform 的位置（去重无效写入）
  const animateTooltip = useCallback(() => {
    // 关键：回调开头先标记"当前帧已结束"。
    // 否则 rAF 因 display:none（如 React 重渲染重置样式）停止续排时，rafRef 会残留旧 id，
    // 导致后续 showTooltip 误判"动画仍在跑"而永不重启 → 悬浮窗消失
    tooltipRafRef.current = null
    const el = tooltipRef.current
    if (!el || el.style.display === 'none') return
    const pos = tooltipPosRef.current
    const target = tooltipTargetRef.current
    // 每帧向目标靠近 14%，形成更大范围的"先快后慢"加速减速跟随；距离足够近时直接贴合
    pos.x += (target.x - pos.x) * 0.06
    pos.y += (target.y - pos.y) * 0.06
    if (Math.abs(target.x - pos.x) < 1.2) pos.x = target.x
    if (Math.abs(target.y - pos.y) < 1.2) pos.y = target.y
    // transform 走合成层（GPU）不触发布局；left/top 会触发 layout，是高频滑动的性能瓶颈
    const applied = tooltipPosAppliedRef.current
    if (applied.x !== pos.x || applied.y !== pos.y) {
      applied.x = pos.x
      applied.y = pos.y
      el.style.transform = `translate3d(${pos.x}px, ${pos.y}px, 0)`
    }
    tooltipRafRef.current = requestAnimationFrame(animateTooltip)
  }, [])
  const showTooltip = useCallback((x, y, html) => {
    const el = tooltipRef.current
    if (!el) return
    // 取消待执行的延迟隐藏（鼠标回到格子区时防抖生效，悬浮窗不闪断）
    if (hideTimerRef.current) {
      clearTimeout(hideTimerRef.current)
      hideTimerRef.current = null
    }
    // 内容去重：同一格子内连续 mousemove 不重建 DOM（大范围滑动时 mousemove 频率极高，避免高频 innerHTML 写入）
    if (el.innerHTML !== html) el.innerHTML = html
    el.style.display = 'block'
    tooltipTargetRef.current = { x, y }
    if (!tooltipRafRef.current) {
      // 首次显示（或 rAF 已停止）时同步定位（transform 避免首帧在左上角闪现），之后移动由 rAF 缓动追赶
      el.style.transform = `translate3d(${x}px, ${y}px, 0)`
      tooltipPosRef.current = { x, y }
      tooltipRafRef.current = requestAnimationFrame(animateTooltip)
    }
  }, [animateTooltip])
  const hideTimerRef = useRef(null)
  const hideTooltip = useCallback(() => {
    // 延迟隐藏防抖：大范围快速移动时鼠标会短暂滑出格子区（月份标签/星期列），
    // 延迟 150ms 后若仍未回来才真正隐藏，避免悬浮窗闪断造成卡顿感
    if (hideTimerRef.current) clearTimeout(hideTimerRef.current)
    hideTimerRef.current = setTimeout(() => {
      hideTimerRef.current = null
      const el = tooltipRef.current
      if (el) el.style.display = 'none'
      if (tooltipRafRef.current) {
        cancelAnimationFrame(tooltipRafRef.current)
        tooltipRafRef.current = null
      }
    }, 150)
  }, [])
  // 组件卸载时取消动画与隐藏定时器，避免泄漏
  useEffect(() => () => {
    if (tooltipRafRef.current) cancelAnimationFrame(tooltipRafRef.current)
    if (hideTimerRef.current) clearTimeout(hideTimerRef.current)
  }, [])

  // ── Calendar year ──────────────────────────────────────────────────
  const latest = batches.filter(s => s.analysis?.summary && s.analysis.summary.total_ups > 0).slice(-1)[0]
  const defaultYear = latest?.created_at
    ? new Date(latest.created_at * 1000).getFullYear()
    : new Date().getFullYear()
  const [selectedYear, setSelectedYear] = useState(defaultYear)

  // ── Fetch calendar data from dedicated API (granular, full-year) ─
  useEffect(() => {
    if (calendarAbortRef.current) {
      calendarAbortRef.current.abort()
    }
    const controller = new AbortController()
    calendarAbortRef.current = controller
    setCalendarStatus('loading')
    setCalendarError('')

    fetch(`/api/up-trends/calendar?year=${selectedYear}`, { signal: controller.signal })
      .then(res => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        return res.json()
      })
      .then(data => {
        if (data?.success) {
          const next = data.data || {}
          setCalendarMap(next)
          setCalendarFetchedAt(data.meta?.fetched_at || null)
          setCalendarStatus(Object.keys(next).length ? 'ready' : 'empty')
        } else {
          throw new Error(data?.message || '日历数据加载失败')
        }
      })
      .catch(err => {
        if (err.name !== 'AbortError') {
          console.error('Calendar fetch failed:', err)
          setCalendarMap({})
          setCalendarError(err.message || '日历数据加载失败')
          setCalendarStatus('error')
        }
      })

    return () => controller.abort()
  }, [refreshToken, selectedYear])

  // 访客无法读取管理员任务状态，定时轻量重拉保证后台任务完成后最终一致。
  useEffect(() => {
    const timer = setInterval(() => setRefreshToken(t => t + 1), 60_000)
    return () => clearInterval(timer)
  }, [])

  // ── Calendar data: 全年发布数据 ──────────────────────────────────
  const calendarData = useMemo(() => {
    const dateMap = new Map() // "YYYY-MM-DD" -> { count, views, batch }

    if (calendarMap && Object.keys(calendarMap).length > 0) {
      Object.entries(calendarMap).forEach(([dateStr, val]) => {
        dateMap.set(dateStr, {
          count: val.count || 0,
          views: val.views || 0,
          batch: 'calendar',
        })
      })
    }

    const dateEntries = []
    dateMap.forEach((val, dateStr) => {
      const parts = dateStr.split('-')
      if (parts.length !== 3) return
      const year = parseInt(parts[0], 10)
      const month = parseInt(parts[1], 10)
      const day = parseInt(parts[2], 10)
      if (isNaN(year) || isNaN(month) || isNaN(day)) return
      const fullDate = new Date(year, month - 1, day)
      dateEntries.push({ dateStr, fullDate, ...val })
    })

    return { dateEntries, refDate: new Date() }
  }, [calendarMap])

  // Build calendar grid: full year (Jan 1 - Dec 31)
  const calendarGrid = useMemo(() => {
    const { dateEntries } = calendarData

    const yearStart = new Date(selectedYear, 0, 1)  // Jan 1
    const yearEnd = new Date(selectedYear, 11, 31)   // Dec 31

    const startDay = yearStart.getDay()
    const mondayOffset = startDay === 0 ? -6 : 1 - startDay
    const gridStart = new Date(yearStart)
    gridStart.setDate(gridStart.getDate() + mondayOffset)

    const endDay = yearEnd.getDay()
    const sundayOffset = endDay === 0 ? 0 : 7 - endDay
    const gridEnd = new Date(yearEnd)
    gridEnd.setDate(gridEnd.getDate() + sundayOffset)

    const lookup = new Map()
    dateEntries.forEach((e) => {
      const key = `${e.fullDate.getFullYear()}-${String(e.fullDate.getMonth() + 1).padStart(2, '0')}-${String(e.fullDate.getDate()).padStart(2, '0')}`
      lookup.set(key, e)
    })

    const weeks = []
    const cursor = new Date(gridStart)
    let maxCount = 0
    let maxViews = 0

    while (cursor <= gridEnd) {
      const week = []
      for (let col = 0; col < 7; col++) {
        const d = new Date(cursor)
        const inYear = d >= yearStart && d <= yearEnd
        const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
        const entry = inYear ? lookup.get(key) : null
        const count = entry ? entry.count : 0
        const views = entry ? entry.views : 0
        if (count > maxCount) maxCount = count
        if (views > maxViews) maxViews = views
        week.push({
          date: new Date(d),
          dateStr: key,
          dateLabel: `${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`,
          count,
          views,
          batch: entry ? entry.batch : null,
          isInRange: inYear,
        })
        cursor.setDate(cursor.getDate() + 1)
      }
      weeks.push(week)
    }

    return { weeks, maxCount, maxViews }
  }, [calendarData, selectedYear])

  // ── Color intensity for calendar heatmap ──
  const getCellColor = (value, maxValue, mode) => {
    if (value === 0) return 'bg-slate-100'
    if (maxValue === 0) return mode === 'views' ? 'bg-blue-200' : 'bg-green-200'
    const ratio = value / maxValue
    if (mode === 'views') {
      if (ratio <= 0.25) return 'bg-blue-200'
      if (ratio <= 0.5) return 'bg-blue-400'
      if (ratio <= 0.75) return 'bg-orange-300'
      return 'bg-orange-500'
    }
    if (ratio <= 0.25) return 'bg-green-200'
    if (ratio <= 0.5) return 'bg-green-300'
    if (ratio <= 0.75) return 'bg-green-500'
    return 'bg-green-600'
  }

  // ── Handlers for heatmap cells ────────────────────────────────────
  const calendarMaxCount = calendarGrid.maxCount
  const calendarMaxViews = calendarGrid.maxViews
  // ── 悬浮窗跟随鼠标（ECharts tooltip 式）：位置随 mousemove 像素级更新，内容随所在格子更新 ──
  const handleCellMove = useCallback((e, cell) => {
    const hasData = cell.count > 0 || cell.views > 0
    // 同款 ECharts tooltip 视觉：白底卡片 + 日期行 + 彩色圆点数值行
    const html = hasData
      ? `<div style="font-size:11px;color:#64748b;margin-bottom:4px">${cell.dateStr}</div>
          <div style="display:flex;align-items:center;gap:8px;line-height:18px">
            <span style="display:inline-block;width:8px;height:8px;background:#22c55e;border-radius:50%"></span>
            <span>发布视频</span>
            <span style="margin-left:12px;font-weight:600">${cell.count} 个</span>
          </div>
          <div style="display:flex;align-items:center;gap:8px;line-height:18px">
            <span style="display:inline-block;width:8px;height:8px;background:#3b82f6;border-radius:50%"></span>
            <span>播放量</span>
            <span style="margin-left:12px;font-weight:600">${formatNumber(cell.views)}</span>
          </div>`
      : `<div style="font-size:11px;color:#94a3b8">${cell.dateStr} · 无发布</div>`
    // 悬浮窗锚定鼠标右上方（左上角定位，偏移更远）；视口边缘不足时翻转到鼠标左下/下方，避免被裁剪
    const tipW = 170
    const tipH = hasData ? 62 : 30
    let x = e.clientX + 20
    let y = e.clientY - 40 - tipH
    if (x + tipW > window.innerWidth - 8) x = e.clientX - 20 - tipW
    if (y < 16) y = e.clientY + 20
    showTooltip(x, y, html)
  }, [showTooltip])
  const handleCellClick = useCallback((cell) => {
    const value = heatmapMode === 'views' ? cell.views : cell.count
    if (value <= 0) return
    setCalendarDetail(cell)
    // 拉取当天发布的视频列表（日历点击 → 视频明细）
    if (dayVideosAbortRef.current) dayVideosAbortRef.current.abort()
    const controller = new AbortController()
    dayVideosAbortRef.current = controller
    setDayVideos(null)
    setDayVideosError(null)
    setDayVideosLoading(true)
    fetch(`/api/up-trends/calendar/day?date=${encodeURIComponent(cell.dateStr)}&limit=50`, { signal: controller.signal })
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        return res.json()
      })
      .then((d) => { if (!controller.signal.aborted) setDayVideos(d?.success ? d.data || [] : []) })
      .catch((e) => {
        if (controller.signal.aborted) return
        // 服务端错误与"当天无数据"区分：错误态显示明确提示，避免误报"暂无明细"
        setDayVideos([])
        setDayVideosError(e?.message ? `加载失败（${e.message}）` : '加载失败')
      })
      .finally(() => { if (!controller.signal.aborted) setDayVideosLoading(false) })
  }, [heatmapMode])

  // 关闭详情面板时取消进行中的请求
  const closeCalendarDetail = useCallback(() => {
    if (dayVideosAbortRef.current) dayVideosAbortRef.current.abort()
    setCalendarDetail(null)
    setDayVideos(null)
    setDayVideosLoading(false)
    setDayVideosError(null)
  }, [])

  // 管理员刷新页面后可继续接管正在运行/排队的持久化任务。
  useEffect(() => {
    if (!isAdmin || activeJobId) return
    let cancelled = false
    api.getActiveCalendarJob().then(res => {
      if (!cancelled && res?.success && res.data) {
        setBackfillJob(res.data)
        setActiveJobId(res.data.id)
        setBackfilling(true)
        setBackfillOk(true)
      }
    })
    return () => { cancelled = true }
  }, [isAdmin, activeJobId])

  // 任务状态以服务端为准；完成后再刷新日历，不再猜测固定 5 秒。
  useEffect(() => {
    if (!activeJobId) return
    let cancelled = false
    let timer = null
    const poll = async () => {
      const res = await api.getCalendarJob(activeJobId)
      if (cancelled) return
      if (!res?.success || !res.data) {
        setBackfillOk(false)
        setBackfillMsg(res?.message || '读取回填任务状态失败')
        setBackfilling(false)
        return
      }
      const job = res.data
      setBackfillJob(job)
      if (job.status === 'queued' || job.status === 'running') {
        setBackfilling(true)
        setBackfillOk(true)
        setBackfillMsg(`回填中 ${job.processed_ups}/${job.total_ups}（${job.progress_percent}%）`)
        timer = setTimeout(poll, 1500)
        return
      }
      setBackfilling(false)
      setBackfillOk(job.status === 'succeeded')
      if (job.status === 'succeeded') {
        setBackfillMsg(`回填完成：${job.total_videos} 个视频，${job.succeeded_ups} 个 UP 成功`)
      } else {
        setBackfillMsg(`回填${job.status === 'partial' ? '部分完成' : '失败'}：失败 ${job.failed_ups}，部分 ${job.partial_ups}`)
      }
      setActiveJobId(null)
      setRefreshToken(t => t + 1)
      onCalendarUpdated?.()
    }
    poll()
    return () => {
      cancelled = true
      if (timer) clearTimeout(timer)
    }
  }, [activeJobId, onCalendarUpdated])

  const handleBackfill = useCallback(async (option) => {
    setBackfillMenuOpen(false)
    if (backfilling) return
    setBackfilling(true)
    setBackfillMsg('')
    const data = await api.calendarBackfill(option)
    if (data?.success) {
      setBackfillOk(true)
      setBackfillJob(data.data || null)
      setActiveJobId(data.job_id)
      setBackfillMsg('回填任务已进入队列')
    } else {
      setBackfillOk(false)
      setBackfillMsg(data?.retry_after ? `请等待 ${data.retry_after} 秒后重试` : (data?.message || '回填启动失败'))
      setBackfilling(false)
    }
  }, [backfilling])

  const handleRetryBackfill = useCallback(async () => {
    if (!backfillJob?.id || backfilling) return
    setBackfilling(true)
    const res = await api.retryCalendarJob(backfillJob.id)
    if (res?.success || (res?.busy && res?.job_id)) {
      setBackfillJob(res.data)
      setActiveJobId(res.job_id)
      setBackfillOk(true)
      setBackfillMsg(res.busy ? '已接管正在执行的重试任务' : '失败项目已重新进入队列')
    } else {
      setBackfilling(false)
      setBackfillOk(false)
      setBackfillMsg(res?.retry_after ? `请等待 ${res.retry_after} 秒后重试` : (res?.message || '重试失败'))
    }
  }, [backfillJob, backfilling])

  return (
    <>
      <ChartCard
        icon={Calendar}
        iconColor="text-orange-500"
        title="发布日历热力图"
        fullWidth
        extra={
          <div className="flex items-center gap-2">
            {/* Year navigation */}
            <div className="flex items-center gap-1">
              <button
                onClick={() => setSelectedYear(y => y - 1)}
                disabled={selectedYear <= 2009}
                className="w-6 h-6 flex items-center justify-center rounded text-slate-400 hover:text-slate-600 hover:bg-slate-100 text-xs"
              >
                ‹
              </button>
              <span className="text-sm font-bold text-slate-700 min-w-[3rem] text-center select-none">
                {selectedYear}
              </span>
              <button
                onClick={() => setSelectedYear(y => y + 1)}
                disabled={selectedYear >= new Date().getFullYear()}
                className="w-6 h-6 flex items-center justify-center rounded text-slate-400 hover:text-slate-600 hover:bg-slate-100 text-xs disabled:opacity-30 disabled:cursor-not-allowed"
              >
                ›
              </button>
            </div>
            {/* Mode toggle */}
            <div className="flex bg-white border border-slate-200 rounded-lg p-0.5">
              <button
                onClick={() => setHeatmapMode('count')}
                className={`px-2.5 py-1 text-xs font-medium rounded-md transition-colors ${heatmapMode === 'count' ? 'bg-green-500 text-white' : 'text-slate-500 hover:bg-slate-50'}`}
              >
                视频数
              </button>
              <button
                onClick={() => setHeatmapMode('views')}
                className={`px-2.5 py-1 text-xs font-medium rounded-md transition-colors ${heatmapMode === 'views' ? 'bg-orange-500 text-white' : 'text-slate-500 hover:bg-slate-50'}`}
              >
                播放量
              </button>
            </div>
            {/* 手动刷新只对管理员可见；访客保留纯读取能力。 */}
            {isAdmin && <div className="relative">
              <button
                onClick={() => setBackfillMenuOpen(o => !o)}
                disabled={backfilling}
                className="flex items-center gap-1 px-2.5 py-1 text-xs font-medium rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-50 disabled:opacity-50 disabled:cursor-not-allowed"
                title="手动刷新日历数据（回填播放量快照）"
              >
                <RefreshCw size={12} className={backfilling ? 'animate-spin' : ''} />
                {backfilling ? '回填中...' : '刷新数据'}
              </button>
              {backfillMenuOpen && (
                <>
                  {/* 透明遮罩：点击外部关闭菜单 */}
                  <div className="fixed inset-0 z-40" onClick={() => setBackfillMenuOpen(false)} />
                  <div className="absolute right-0 top-full mt-1 z-50 bg-white border border-slate-200 rounded-lg shadow-lg py-1 min-w-[9rem]">
                    {[
                      { label: '最近 7 天', mode: 'recent', days: 7, tip: '快速刷新' },
                      { label: '最近 30 天', mode: 'recent', days: 30, tip: '刷新近期播放量' },
                      { label: `${selectedYear} 全年`, mode: 'year', year: selectedYear, tip: '完整刷新与对账' },
                    ].map(opt => (
                      <button
                        key={opt.label}
                        onClick={() => handleBackfill(opt)}
                        className="w-full text-left px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-50 flex items-center justify-between gap-2"
                      >
                        <span>{opt.label}</span>
                        <span className="text-[10px] text-slate-400">{opt.tip}</span>
                      </button>
                    ))}
                  </div>
                </>
              )}
            </div>}
          </div>
        }
      >
        {backfillMsg && (
          <div className={`text-xs rounded-lg px-3 py-1.5 mb-2 flex items-center gap-2 ${backfillOk ? 'text-green-700 bg-green-50' : 'text-red-600 bg-red-50'}`}>
            <RefreshCw size={12} className={backfilling ? 'animate-spin' : ''} />
            <span>{backfillMsg}</span>
            {!backfilling && backfillJob && ['failed', 'partial'].includes(backfillJob.status) && isAdmin && (
              <button onClick={handleRetryBackfill} className="ml-auto underline underline-offset-2">重试失败项</button>
            )}
          </div>
        )}
        <div>
            <div className="min-h-[20px] mb-1 pl-6 text-[10px] text-slate-400 flex items-center gap-2">
              {calendarStatus === 'loading' && <span>正在加载 {selectedYear} 年数据…</span>}
              {calendarStatus === 'empty' && <span>{selectedYear} 年暂无发布记录，灰色格子仍表示完整日期。</span>}
              {calendarStatus === 'error' && (
                <span className="text-red-500">加载失败：{calendarError}</span>
              )}
              {calendarFetchedAt && calendarStatus !== 'loading' && (
                <span>数据更新于 {new Date(calendarFetchedAt * 1000).toLocaleString('zh-CN')}</span>
              )}
              {calendarStatus === 'error' && (
                <button onClick={() => setRefreshToken(t => t + 1)} className="text-primary-600 underline underline-offset-2">重试</button>
              )}
            </div>
            {/* GitHub-style contribution heatmap */}
            <div className="flex min-w-0">
              {/* Day-of-week labels on the left */}
              <div className="flex flex-col justify-center gap-[3px] pt-[22px] pr-2 flex-shrink-0">
                {['一', '二', '三', '四', '五', '六', '日'].map((day, i) => (
                  <div key={i} className="h-3 flex items-center">
                    <span className="text-[10px] text-slate-400 w-4 text-right">{i % 2 === 0 ? day : ''}</span>
                  </div>
                ))}
              </div>

              {/* Scrollable weeks area */}
              <div className="overflow-x-auto pb-2 flex-1 min-w-0">
                {/* 隐藏范围覆盖月份标签行+格子区：鼠标在整个日历区域内滑动都不闪断，离开整个区域才触发延迟隐藏 */}
                <div className="inline-flex flex-col" onMouseLeave={hideTooltip}>
                  {/* Month labels */}
                  <div className="flex gap-[3px] h-[18px] mb-[3px]">
                    {calendarGrid.weeks.map((week, wi) => {
                      const firstDay = week[0]
                      const prevWeek = calendarGrid.weeks[wi - 1]
                      const prevMonth = prevWeek ? prevWeek[0].date.getMonth() : -1
                      const showMonth = firstDay.isInRange && firstDay.date.getMonth() !== prevMonth
                      return (
                        <div key={wi} className="w-3 flex-shrink-0">
                          {showMonth && (
                            <span className="text-[10px] text-slate-400 whitespace-nowrap">
                              {firstDay.date.getMonth() + 1}月
                            </span>
                          )}
                        </div>
                      )
                    })}
                  </div>

                  {/* Heatmap cells */}
                  <div className="flex gap-[3px]">
                    {calendarGrid.weeks.map((week, wi) => (
                      <div key={wi} className="flex flex-col gap-[3px]">
                        {week.map((cell, ci) => {
                          const value = heatmapMode === 'views' ? cell.views : cell.count
                          const maxVal = heatmapMode === 'views' ? calendarMaxViews : calendarMaxCount
                          const colorClass = getCellColor(value, maxVal, heatmapMode)
                          const hoverClass = cell.isInRange
                            ? colorClass + (value > 0 ? ' hover:ring-1 hover:ring-slate-400 hover:scale-125' : ' hover:ring-1 hover:ring-slate-300')
                            : 'bg-transparent'
                          return (
                            <div
                              key={ci}
                              // transition 只监听 transform/box-shadow：578 个格子快速掠过时动画排队少、开销低
                              className={`w-3 h-3 rounded-sm flex-shrink-0 transition-[transform,box-shadow] cursor-pointer ${hoverClass}`}
                              onClick={() => handleCellClick(cell)}
                              onMouseEnter={(e) => handleCellMove(e, cell)}
                              onMouseMove={(e) => handleCellMove(e, cell)}
                            />
                          )
                        })}
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>

            {/* Legend */}
            <div className="flex items-center gap-2 mt-3 text-[10px] text-slate-400 pl-6">
              <span>少</span>
              {heatmapMode === 'views' ? (
                <>
                  <div className="w-3 h-3 rounded-sm bg-slate-100" />
                  <div className="w-3 h-3 rounded-sm bg-blue-200" />
                  <div className="w-3 h-3 rounded-sm bg-blue-400" />
                  <div className="w-3 h-3 rounded-sm bg-orange-300" />
                  <div className="w-3 h-3 rounded-sm bg-orange-500" />
                </>
              ) : (
                <>
                  <div className="w-3 h-3 rounded-sm bg-slate-100" />
                  <div className="w-3 h-3 rounded-sm bg-green-200" />
                  <div className="w-3 h-3 rounded-sm bg-green-300" />
                  <div className="w-3 h-3 rounded-sm bg-green-500" />
                  <div className="w-3 h-3 rounded-sm bg-green-600" />
                </>
              )}
              <span>多</span>
              <span className="ml-2">
                ({heatmapMode === 'views'
                  ? `${formatNumber(calendarGrid.maxViews)} 播放/天`
                  : `${calendarGrid.maxCount} 视频/天`})
              </span>
            </div>

            {/* Annotation */}
            <p className="text-[10px] text-slate-400 mt-2 pl-6">
              {heatmapMode === 'views'
                ? '播放量为视频截止最新分析的累计数据，较早发布的视频因累积时间长数值会偏高'
                : '视频数为当天发布的数量'}
            </p>

            {/* Detail popup */}
            {calendarDetail && (
              <div className="mt-4 p-4 bg-slate-50 rounded-lg border border-slate-200">
                <div className="flex items-center justify-between mb-3">
                  <h4 className="text-sm font-bold text-slate-700">
                    {calendarDetail.dateStr} 发布详情
                  </h4>
                  <button
                    onClick={closeCalendarDetail}
                    className="text-slate-400 hover:text-slate-600 text-xs"
                  >
                    关闭
                  </button>
                </div>
                <div className="text-sm text-slate-600 mb-3">
                  共 <strong className="text-green-600">{calendarDetail.count}</strong> 个视频 ·{' '}
                  <strong className="text-blue-600">{formatNumber(calendarDetail.views)}</strong> 播放
                </div>

                {/* 当天视频列表（按播放量降序） */}
                {dayVideosLoading && (
                  <p className="text-xs text-slate-400 py-2 flex items-center gap-2">
                    <span className="inline-block w-3 h-3 border-2 border-primary-500 border-t-transparent rounded-full animate-spin" />
                    加载当天视频...
                  </p>
                )}
                {!dayVideosLoading && dayVideos && dayVideos.length === 0 && (
                  <p className="text-xs text-slate-400 py-2">{dayVideosError || '暂无视频明细（该天无回填记录）'}</p>
                )}
                {!dayVideosLoading && dayVideos && dayVideos.length > 0 && (
                  <div className="space-y-0.5 max-h-72 overflow-y-auto pr-1">
                    {dayVideos.map((v, i) => (
                      <a
                        key={v.bvid}
                        href={`https://www.bilibili.com/video/${v.bvid}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="flex items-center gap-2 px-2 py-1.5 rounded hover:bg-white transition-colors group"
                      >
                        <span className="w-5 text-xs text-slate-400 text-right tabular-nums shrink-0">{i + 1}</span>
                        <span className="flex-1 min-w-0 text-sm text-slate-700 truncate group-hover:text-primary-600">{v.title}</span>
                        <span className="text-xs text-slate-500 tabular-nums shrink-0">{formatNumber(v.views)}</span>
                        <ExternalLink size={12} className="text-slate-300 group-hover:text-primary-400 shrink-0" />
                      </a>
                    ))}
                  </div>
                )}

                {calendarDetail.batch && (
                  <p className="text-xs text-slate-400 mt-2">
                    数据来源: {calendarDetail.batch} 批次
                  </p>
                )}
              </div>
            )}

            {/* ── 发布频率折线图 ── */}
            <FrequencyLineChart
              weeks={calendarGrid.weeks}
              heatmapMode={heatmapMode}
              selectedYear={selectedYear}
              formatNumber={formatNumber}
            />
          </div>
      </ChartCard>

      {/* Portal 到 body：避免页面入场动画的 transform 改写 fixed 后代的包含块，
          否则滚动到日历后，clientX/clientY 会被再次叠加文档滚动偏移，Tooltip 跑到视口外。 */}
      {createPortal(
        <div
          ref={tooltipRef}
          className="fixed z-50 pointer-events-none rounded-lg whitespace-nowrap"
          style={{
            display: 'none',
            left: 0,
            top: 0,
            background: 'rgba(255,255,255,0.96)',
            border: '1px solid #e2e8f0',
            color: '#334155',
            fontSize: 11,
            padding: '8px 10px',
            boxShadow: '0 4px 12px rgba(0,0,0,0.12)',
            willChange: 'transform',
          }}
        />,
        document.body,
      )}
    </>
  )
}

// ════════════════════════════════════════════════════════════════════
// 卡片2：活跃UP主变化折线
// ════════════════════════════════════════════════════════════════════
export function ActiveUpCard({ batches = [] }) {
  const { activeData, singleMode } = useBatchData(batches)

  // Y 轴自动缩放：活跃UP数波动较小（如 20→25），取 [min-2, max+2] 让起伏可见
  const activeMin = Math.max(0, Math.min(...activeData.map(d => d.count), 0) - 2)
  const activeMax = Math.max(1, Math.max(...activeData.map(d => d.count), 1) + 2)

  const activeOption = useMemo(() => (
    activeData.length >= 2 ? buildLineTrendOption({
      data: activeData.map(d => ({ date: d.date, value: d.count })),
      color: '#22c55e',
      startColor: 'rgba(34,197,94,0.22)',
      yMin: activeMin,
      yMax: activeMax,
      labelColor: '#15803d',
      tooltipFormatter: (params) => {
        const d = activeData[params[0].dataIndex]
        return `<div style="font-size:11px;color:#64748b;margin-bottom:4px">${d.date}</div>
          <div style="display:flex;align-items:center;gap:8px;line-height:18px">
            <span style="display:inline-block;width:8px;height:8px;background:#22c55e;border-radius:50%"></span>
            <span>活跃UP主</span>
            <span style="margin-left:12px;font-weight:600">${d.count} 位</span>
          </div>`
      },
    }) : null
  ), [activeData, activeMin, activeMax])

  return (
    <ChartCard icon={Users} iconColor="text-green-500" title="活跃UP主变化" note={singleMode ? '需要至少2次分析才能展示趋势' : null}>
      {singleMode ? (
        <div className="flex items-center justify-center py-8 text-slate-400 text-sm">
          需要至少2次分析才能展示趋势
        </div>
      ) : (
        <div className="relative">
          <div className="flex items-center justify-end mb-1 pr-1">
            <span className="text-[10px] text-slate-400 flex items-center gap-1">
              <span className="w-2.5 h-2.5 rounded-sm inline-block" style={{ background: '#22c55e' }} />
              活跃UP主（近7天有发布）
            </span>
          </div>
          <EChart option={activeOption} height={200} />
        </div>
      )}
    </ChartCard>
  )
}

// ════════════════════════════════════════════════════════════════════
// 卡片3：鬼畜视频占比（比例条 + 趋势折线）
// ════════════════════════════════════════════════════════════════════
export function KichuRatioCard({ batches = [] }) {
  const { kichuRatioData, latestKichu, kichuPct, singleMode } = useBatchData(batches)

  // 鬼畜占比 Y 轴自动缩放：占比波动（如 25%→45%）从 0 起偏平，取 [min-5%, max+5%] 放大变化
  const ratioMin = Math.max(0, Math.min(...kichuRatioData.map(d => d.ratio * 100), 0) - 5)
  const ratioMax = Math.max(1, Math.max(...kichuRatioData.map(d => d.ratio * 100), 1) + 5)

  const kichuOption = useMemo(() => (
    kichuRatioData.length >= 2 ? buildLineTrendOption({
      data: kichuRatioData.map(d => ({ date: d.date, value: +(d.ratio * 100).toFixed(1) })),
      color: '#00AEEC',
      startColor: 'rgba(0,174,236,0.2)',
      yMin: ratioMin,
      yMax: ratioMax,
      labelColor: '#00AEEC',
      hideOverlappingLabels: true,
      yLabelFmt: (v) => v + '%',
      // series label formatter 收到的是 params 对象，需取 .value
      labelFmt: (p) => p.value + '%',
      tooltipFormatter: (params) => {
        const d = kichuRatioData[params[0].dataIndex]
        const val = (d.ratio * 100).toFixed(1)
        return `<div style="font-size:11px;color:#64748b;margin-bottom:4px">${d.date}</div>
          <div style="display:flex;align-items:center;gap:8px;line-height:18px">
            <span style="display:inline-block;width:8px;height:8px;background:#00AEEC;border-radius:50%"></span>
            <span>鬼畜视频占比</span>
            <span style="margin-left:12px;font-weight:600">${val}%</span>
          </div>
          <div style="font-size:10px;color:#94a3b8;margin-top:2px">鬼畜 ${d.kichu} / ${d.total} 个视频</div>`
      },
    }) : null
  ), [kichuRatioData, ratioMin, ratioMax])

  return (
    <ChartCard icon={Sparkles} iconColor="text-primary-500" title="鬼畜视频占比" note={singleMode ? '需要至少2次分析才能展示趋势' : null}>
      {singleMode ? (
        <div className="flex items-center justify-center py-8 text-slate-400 text-sm">
          需要至少2次分析才能展示趋势
        </div>
      ) : (
        <div className="space-y-3">
          {/* 双段比例条：鬼畜（蓝） + 非鬼畜（灰） */}
          <div>
            <div className="flex items-center justify-between mb-1.5 text-xs text-slate-500">
              <span>
                鬼畜 <strong className="text-primary-600">{latestKichu.kichu}</strong> / {latestKichu.total} 个视频
              </span>
              <span className="font-bold text-primary-600">{kichuPct}%</span>
            </div>
            <div className="w-full h-4 bg-slate-100 rounded-full overflow-hidden flex">
              <div
                className="h-full bg-gradient-to-r from-primary-400 to-primary-500 transition-all duration-500"
                style={{ width: `${Math.max(1, latestKichu.ratio * 100)}%` }}
              />
              {latestKichu.ratio < 1 && (
                <div
                  className="h-full bg-slate-200 transition-all duration-500"
                  style={{ width: `${Math.max(1, (1 - latestKichu.ratio) * 100)}%` }}
                />
              )}
            </div>
            <div className="flex items-center justify-between mt-1 text-[10px] text-slate-400">
              <span>鬼畜 {kichuPct}%</span>
              <span>非鬼畜 {(100 - parseFloat(kichuPct)).toFixed(1)}%</span>
            </div>
          </div>

          {latestKichu.kichu >= latestKichu.total && latestKichu.total > 0 && (
            <p className="text-[10px] text-amber-500">注：当前批次鬼畜视频统计字段尚在迁移中，占比为近似参考值，下次刷新后数据将更精准</p>
          )}

          {/* Divider */}
          <div className="border-t border-slate-100" />

          {/* 占比趋势折线（Y轴自动缩放放大波动） */}
          <div>
            <div className="flex items-center justify-end mb-1 pr-1">
              <span className="text-[10px] text-slate-400 flex items-center gap-1">
                <span className="w-2.5 h-2.5 rounded-sm inline-block" style={{ background: '#00AEEC' }} />
                鬼畜视频占比
              </span>
            </div>
            <EChart option={kichuOption} height={200} />
          </div>
        </div>
      )}
    </ChartCard>
  )
}

// ════════════════════════════════════════════════════════════════════
// 卡片4：播放量排行变化（正负对称柱）
// ════════════════════════════════════════════════════════════════════
export function PlayRankingChangeCard({ batches = [] }) {
  const { rankingData, previous } = useBatchData(batches)

  const rankingOption = useMemo(() => (
    rankingData.length > 0 ? buildRankingBarOption(rankingData, formatChange, formatNumber) : null
  ), [rankingData])

  return (
    <ChartCard icon={Trophy} iconColor="text-yellow-500" title="播放量排行变化">
      {rankingData.length === 0 ? (
        <div className="text-center py-8 text-slate-400 text-sm">暂无排行数据</div>
      ) : (
        <EChart option={rankingOption} height={Math.max(rankingData.length * 34, 200)} />
      )}
      {rankingData.length > 0 && previous && (
        <p className="text-xs text-slate-400 mt-2">
          按播放量变化幅度排序，对比上次的播放量名次与播放量变化，🆕 表示新进入TOP10
        </p>
      )}
    </ChartCard>
  )
}

// ── 折线趋势 option 工厂：折线类图表共用，避免配置重复 ─────────────
// 统一风格：平滑曲线 + 渐变面积 + 逐点数值标签 + 末点强调 + axis tooltip
function buildLineTrendOption({ data, color, startColor, yMin, yMax, labelColor, yLabelFmt, labelFmt, tooltipFormatter, hideOverlappingLabels = false }) {
  if (!data || data.length < 2) return null
  return {
    grid: { left: 42, right: 30, top: 26, bottom: 22 },
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(255,255,255,0.96)',
      borderColor: '#e2e8f0',
      textStyle: { fontSize: 11, color: '#334155' },
      formatter: tooltipFormatter,
    },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: data.map(d => d.date),
      axisLabel: { fontSize: 10, color: '#94a3b8' },
      axisLine: { lineStyle: { color: '#e2e8f0' } },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value',
      min: yMin,
      max: yMax,
      axisLabel: { fontSize: 10, color: '#94a3b8', formatter: yLabelFmt },
      splitLine: { lineStyle: { color: '#f1f5f9' } },
    },
    series: [{
      type: 'line',
      data: data.map(d => d.value),
      smooth: true,
      symbol: 'circle',
      symbolSize: (value, params) => (params.dataIndex === data.length - 1 ? 7 : 5),
      itemStyle: { color },
      lineStyle: { width: 2, color },
      label: {
        show: true,
        position: 'top',
        distance: 8,
        fontSize: 11,
        fontWeight: 600,
        color: labelColor,
        formatter: labelFmt,
        // 字体实测高度可能高于图表的测量值，留少量安全间距。
        ...(hideOverlappingLabels ? { padding: [2, 3], backgroundColor: 'transparent' } : {}),
      },
      // 按实际标签包围盒避让，resize 后重新计算。末点符号较大，
      // ECharts 按符号面积排序避让，优先保留最新数值。
      ...(hideOverlappingLabels ? {
        showAllSymbol: true,
        labelLayout: { hideOverlap: true },
      } : {}),
      areaStyle: {
        color: {
          type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [
            { offset: 0, color: startColor },
            { offset: 1, color: 'rgba(255,255,255,0)' },
          ],
        },
      },
      // 末点强调：外圈描边圆环
      markPoint: {
        symbol: 'circle',
        symbolSize: 16,
        itemStyle: { color: 'rgba(255,255,255,0.01)', borderColor: color, borderWidth: 1.5 },
        label: { show: false },
        data: [{ coord: [data.length - 1, data[data.length - 1].value] }],
      },
    }],
  }
}

// ── 播放量排行变化 option：正负对称柱（中线为0，正值绿向右 / 负值红向左）──
function buildRankingBarOption(items, formatChange, formatNumber) {
  // ECharts category 轴自底向上排列 → reverse 让第 1 名显示在顶部
  const reversed = [...items].reverse()
  const rankMap = new Map(items.map(u => [u.name, u]))
  const maxAbs = Math.max(...items.map(u => Math.abs(u.viewsChange || 0)), 1)
  const pad = maxAbs * 0.18

  const barLabelFmt = (p) => {
    const u = rankMap.get(p.name)
    if (!u || u.viewsChange == null) return ''
    const base = formatChange(u.viewsChange)
    const pct = u.viewsChangePct != null
      ? `${u.viewsChangePct >= 0 ? '+' : ''}${u.viewsChangePct.toFixed(1)}%`
      : ''
    return pct ? `${base} · ${pct}` : base
  }

  // ECharts v5+ 的 label.color 不接受函数回调（静默忽略、回退默认色 → 黑字），
  // 因此把颜色/位置/描边全部下沉到数据项级 label（普通对象，按数据点独立生效）
  const INSIDE_RATIO = 0.35
  const insideThreshold = maxAbs * INSIDE_RATIO
  // 为单个数据点构建 { value, name, label }：柱子长度 > 阈值 → 文字在柱内(白)，
  // 否则在柱外(与柱子同色)。上升=绿(#22c55e) / 下降=红(#f87171)
  const toBarItem = (u, isPositive) => {
    const v = u.viewsChange || 0
    if (isPositive ? v <= 0 : v >= 0) return null
    const barColor = isPositive ? '#22c55e' : '#f87171'
    const inside = Math.abs(v) > insideThreshold
    return {
      value: v,
      name: u.name,
      label: {
        show: true,
        position: inside ? (isPositive ? 'insideRight' : 'insideLeft') : (isPositive ? 'right' : 'left'),
        color: inside ? '#fff' : barColor,
        fontSize: 10,
        fontWeight: 600,
        formatter: barLabelFmt,
      },
    }
  }

  return {
    grid: { left: 8, right: 104, top: 8, bottom: 22, containLabel: true },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      backgroundColor: 'rgba(255,255,255,0.96)',
      borderColor: '#e2e8f0',
      textStyle: { fontSize: 11, color: '#334155' },
      formatter: (params) => {
        const u = rankMap.get(params[0].name)
        if (!u) return ''
        const rankChange = u.rankState === 'new'
          ? '<span style="color:#22c55e;font-weight:600">🆕 新上榜</span>'
          : u.rankState === 'n/a'
            ? '<span style="color:#94a3b8;font-weight:600">播放量名次对比: 历史批次无播放量排行</span>'
            : `<span style="color:${u.change.arrow === '↑' ? '#16a34a' : u.change.arrow === '↓' ? '#dc2626' : '#94a3b8'};font-weight:600">播放量名次: ${u.change.arrow} ${u.change.diff > 0 ? u.change.diff : '持平'}</span>`
        const changeLine = u.viewsChange == null
          ? '<div style="color:#94a3b8">播放量变化: —</div>'
          : `<div style="color:${u.viewsChange >= 0 ? '#16a34a' : '#dc2626'};font-weight:600">播放量变化: ${formatChange(u.viewsChange)}${u.viewsChangePct != null ? ` (${u.viewsChangePct >= 0 ? '+' : ''}${u.viewsChangePct.toFixed(1)}%)` : ''}</div>`
        return `<div style="font-size:12px;font-weight:700;color:#334155;margin-bottom:4px">${u.name}</div>
          ${rankChange}
          ${changeLine}
          <div style="color:#64748b">当前播放量: <b>${formatNumber(u.total_recent_views)}</b></div>`
      },
    },
    xAxis: {
      type: 'value',
      min: -maxAbs - pad,
      max: maxAbs + pad,
      minInterval: 1,
      axisLabel: {
        fontSize: 9,
        color: '#94a3b8',
        formatter: (v) => {
          const abs = Math.abs(v)
          if (abs >= 10000) return (v < 0 ? '-' : '') + (abs / 10000).toFixed(1) + '万'
          return v
        },
      },
      splitLine: { lineStyle: { color: '#f1f5f9' } },
    },
    yAxis: {
      type: 'category',
      data: reversed.map(u => u.name),
      axisLabel: {
        fontSize: 11,
        color: '#475569',
        // 固定行高 + 垂直居中：避免 🆕 emoji 字形偏高把文字基线顶偏，
        // 保证名字与柱子中线严格对齐（仅 🆕 影响基线，奖牌已移除）
        lineHeight: 14,
        verticalAlign: 'middle',
        formatter: (name) => {
          const u = rankMap.get(name)
          if (!u) return name
          // Y 轴按变化幅度排序，显示 changeRank（连续 1-10）；不用奖牌——奖牌语义属
          // 播放量榜，且下降幅度大也排前面，给"跌得最多"发 🥇 会误导。currentRank（播放量
          // 名次）保留在 tooltip 展示，与 prevRank 同口径算 ↑↓。
          const newMark = u.rankState === 'new' ? ' 🆕' : ''
          return `${u.changeRank}. ${name}${newMark}`
        },
      },
      axisLine: { show: false },
      axisTick: { show: false },
    },
    series: [
      {
        name: '增长',
        type: 'bar',
        data: reversed.map(u => toBarItem(u, true)),
        barWidth: 14,
        // 两个 series 共用同一槽位（默认并排会把正/负柱分别挤到上/下半槽，看起来没居中）
        barGap: '-100%',
        itemStyle: { color: '#22c55e', borderRadius: [0, 3, 3, 0] },
      },
      {
        name: '下降',
        type: 'bar',
        data: reversed.map(u => toBarItem(u, false)),
        barWidth: 14,
        itemStyle: { color: '#f87171', borderRadius: [3, 0, 0, 3] },
      },
    ],
  }
}

const FREQUENCY_RANGES = [
  { key: '30d', label: '近30天', days: 30, granularity: 'day' },
  { key: '90d', label: '近90天', days: 90, granularity: 'day' },
  { key: '180d', label: '近半年', days: 180, granularity: 'week' },
  { key: 'year', label: '全年', days: null, granularity: 'week' },
]

// 按区间生成发布趋势：短区间保留日粒度，长区间按热力图自然周聚合。
// 导出纯函数便于回归测试，避免未来再次把全年 365 个点直接塞进折线图。
export function buildFrequencySeries(weeks, selectedYear, rangeKey, now = new Date()) {
  const range = FREQUENCY_RANGES.find(item => item.key === rangeKey) || FREQUENCY_RANGES[1]
  const yearStart = new Date(selectedYear, 0, 1)
  const yearEnd = new Date(selectedYear, 11, 31)
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const endDate = selectedYear === today.getFullYear() && today < yearEnd ? today : yearEnd
  const startDate = new Date(yearStart)
  if (range.days) {
    startDate.setTime(endDate.getTime())
    startDate.setDate(startDate.getDate() - range.days + 1)
    if (startDate < yearStart) startDate.setTime(yearStart.getTime())
  }

  const isVisible = cell => cell.isInRange && cell.date >= startDate && cell.date <= endDate
  if (range.granularity === 'day') {
    return {
      data: weeks.flatMap(week => week)
        .filter(isVisible)
        .map(cell => ({
          date: cell.date,
          dateStr: cell.dateStr,
          endDateStr: cell.dateStr,
          count: cell.count,
          views: cell.views,
        })),
      granularity: 'day',
      rangeLabel: range.label,
    }
  }

  const points = []
  weeks.forEach((week) => {
    const visibleCells = week.filter(isVisible)
    if (!visibleCells.length) return
    points.push({
      date: visibleCells[0].date,
      dateStr: visibleCells[0].dateStr,
      endDateStr: visibleCells[visibleCells.length - 1].dateStr,
      count: visibleCells.reduce((sum, cell) => sum + cell.count, 0),
      views: visibleCells.reduce((sum, cell) => sum + cell.views, 0),
    })
  })
  return { data: points, granularity: 'week', rangeLabel: range.label }
}

// ── 发布频率折线图组件（短区间按日、长区间按周，平滑曲线 + tooltip + 渐变面积）──
function FrequencyLineChart({ weeks, heatmapMode, selectedYear, formatNumber }) {
  const [rangeKey, setRangeKey] = useState('90d')
  const { data, granularity, rangeLabel } = useMemo(
    () => buildFrequencySeries(weeks, selectedYear, rangeKey),
    [weeks, selectedYear, rangeKey],
  )

  if (data.length === 0) return null

  const valueKey = heatmapMode === 'views' ? 'views' : 'count'
  const values = data.map(d => d[valueKey])
  const maxVal = Math.max(...values, 1)
  const lineColor = heatmapMode === 'views' ? '#f97316' : '#10b981'
  const unitLabel = granularity === 'day' ? '日' : '周'
  const seriesLabel = heatmapMode === 'views' ? `${unitLabel}播放量` : `${unitLabel}发布量`

  const option = useMemo(() => ({
    grid: { left: 44, right: 16, top: 18, bottom: 22 },
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(255,255,255,0.96)',
      borderColor: '#e2e8f0',
      textStyle: { fontSize: 11, color: '#334155' },
      formatter: (params) => {
        const p = params[0]
        const d = data[p.dataIndex]
        // category 轴 + 单值 series：p.value 是数值本身，直接按索引取原始数据
        const raw = d ? d[valueKey] : null
        const valStr = valueKey === 'views' ? formatNumber(raw) : `${raw} 个`
        const dateLabel = granularity === 'week' && d.endDateStr !== d.dateStr
          ? `${d.dateStr} 至 ${d.endDateStr}`
          : d.dateStr
        return `<div style="font-size:11px;color:#64748b;margin-bottom:4px">${dateLabel}</div>
          <div style="display:flex;align-items:center;gap:8px;line-height:18px">
            <span style="display:inline-block;width:8px;height:8px;background:${lineColor};border-radius:50%"></span>
            <span>${seriesLabel}</span>
            <span style="margin-left:12px;font-weight:600">${valStr}</span>
          </div>`
      },
    },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: data.map(d => d.dateStr),
      axisLabel: {
        fontSize: 9,
        color: '#94a3b8',
        // 日粒度近30天每5个点显示月/日；其他区间按月显示首个点。
        formatter: (val, idx) => {
          const d = data[idx]
          const prev = idx > 0 ? data[idx - 1] : null
          if (granularity === 'day' && rangeKey === '30d') {
            return idx % 5 === 0 || idx === data.length - 1
              ? `${d.date.getMonth() + 1}/${d.date.getDate()}`
              : ''
          }
          return prev && d.date.getMonth() === prev.date.getMonth() ? '' : `${d.date.getMonth() + 1}月`
        },
      },
      axisLine: { lineStyle: { color: '#e2e8f0' } },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value',
      minInterval: 1,
      axisLabel: {
        fontSize: 9,
        color: '#94a3b8',
        formatter: (v) => (valueKey === 'views' && v >= 10000 ? (v / 10000).toFixed(1) + '万' : v),
      },
      splitLine: { lineStyle: { color: '#f1f5f9' } },
    },
    series: [{
      type: 'line',
      data: data.map(d => d[valueKey]),
      smooth: granularity === 'day' ? 0.28 : true,
      symbol: 'circle',
      symbolSize: 4,
      itemStyle: { color: lineColor },
      lineStyle: { width: 2, color: lineColor },
      areaStyle: {
        color: {
          type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [
            { offset: 0, color: heatmapMode === 'views' ? 'rgba(249,115,22,0.18)' : 'rgba(16,185,129,0.18)' },
            { offset: 1, color: 'rgba(255,255,255,0)' },
          ],
        },
      },
    }],
  }), [data, valueKey, lineColor, seriesLabel, heatmapMode, formatNumber, granularity, rangeKey])

  return (
    <div className="mt-4 pt-3 border-t border-slate-100">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <p className="text-[10px] text-slate-400 font-medium tracking-wide">
          {selectedYear}年 {seriesLabel}趋势 · {rangeLabel}
          <span className="ml-2 font-normal">
            {valueKey === 'views'
              ? `最高 ${formatNumber(maxVal)} 播放/${unitLabel}`
              : `最高 ${maxVal} 个/${unitLabel}`}
          </span>
        </p>
        <div className="flex items-center rounded-lg border border-slate-200 bg-white p-0.5" aria-label="发布趋势时间区间">
          {FREQUENCY_RANGES.map(item => (
            <button
              key={item.key}
              type="button"
              aria-pressed={rangeKey === item.key}
              onClick={() => setRangeKey(item.key)}
              className={`rounded-md px-2.5 py-1 text-[10px] font-medium transition-colors ${
                rangeKey === item.key
                  ? 'bg-primary-500 text-white shadow-sm'
                  : 'text-slate-500 hover:bg-primary-50 hover:text-primary-600'
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>
      <EChart option={option} height={130} />
    </div>
  )
}

// ── 迷你趋势折线（StatCard 卡片内嵌，纯展示无交互）──
export function MiniSparkLine({ data, color = '#3b82f6', height = 40 }) {
  const gradientId = useMemo(() => 'spark-' + Math.random().toString(36).slice(2, 8), [])
  if (!data || data.length < 2) return null

  const W = 200
  const H = height
  const PAD = 4
  // 与展开大图 buildTrendOption 同口径：基于真实数据区间 ±15% 边距，不再锚定 0 底，
  // 使预览折线与展开图 Y 轴缩放一致（形状、起伏幅度对齐）
  const nums = data.filter(v => v !== null && v !== undefined && !isNaN(v))
  if (nums.length < 2) return null
  const rawMin = Math.min(...nums)
  const rawMax = Math.max(...nums)
  const pad = Math.max((rawMax - rawMin) * 0.15, 1)
  const min = rawMin - pad
  const max = rawMax + pad
  const range = (max - min) || 1
  const points = data.map((v, i) => {
    const x = PAD + (i / (data.length - 1)) * (W - PAD * 2)
    const y = (v == null) ? (H - PAD) : (PAD + (H - PAD * 2) - ((v - min) / range) * (H - PAD * 2))
    return `${x.toFixed(1)},${y.toFixed(1)}`
  })
  const areaPoints = `${PAD},${H - PAD} ${points.join(' ')} ${W - PAD},${H - PAD}`

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto" preserveAspectRatio="none" style={{ height: `${H}px` }}>
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.25" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <polygon points={areaPoints} fill={`url(#${gradientId})`} />
      <polyline points={points.join(' ')} fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round" />
    </svg>
  )
}
