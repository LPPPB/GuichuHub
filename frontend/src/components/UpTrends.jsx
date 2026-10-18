import { motion } from 'framer-motion'
import { createPortal } from 'react-dom'
import { useState, useEffect, useCallback, useMemo, useRef, Component } from 'react'
import { api } from '../utils/api'
import {
  Users, Video, TrendingUp, RefreshCw, ExternalLink, Eye,
  Flame, BarChart3, Cloud, Trophy, Calendar, Sparkles, Settings,
  List, AlertTriangle, ZoomIn, ZoomOut, RotateCcw, Activity,
  ChevronDown, ChevronUp, Clock, Rocket, UserPlus, ClipboardCheck,
  X, Minus
} from 'lucide-react'
import UpRequestModal from './UpRequestModal'
import ObservationRoster from './ObservationRoster'
import { PublishCalendarCard, ActiveUpCard, KichuRatioCard, PlayRankingChangeCard, MiniSparkLine, formatNumber, formatDate } from './TrendCharts'
import EChart from './EChart'
import { computeSpiralPositions } from '../utils/wordCloud'
import { useResizableHeight } from '../utils/useResizableHeight'
import { buildUpTrendsNarrative } from '../utils/upTrendsNarrative'
import { IslandProvider, IslandAnchor, IslandOverlay, useIsland } from './DynamicIsland'

// 错误边界：避免整个应用因 UpTrends 异常而白屏
class UpTrendsErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, error: null }
  }
  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }
  render() {
    if (this.state.hasError) {
      return (
        <div className="flex flex-col items-center justify-center py-20">
          <AlertTriangle className="text-red-400 mb-4" size={48} />
          <p className="text-slate-700 font-medium mb-2">UP主动态加载失败</p>
          <p className="text-sm text-slate-500 mb-1 max-w-md text-center">{this.state.error?.message || '未知错误'}</p>
          {this.state.error?.stack && (
            <pre className="text-xs text-slate-400 mt-2 p-3 bg-slate-50 rounded-lg max-w-lg overflow-auto max-h-32">
              {this.state.error.stack}
            </pre>
          )}
          <button
            onClick={() => this.setState({ hasError: false, error: null })}
            className="px-4 py-2 bg-primary-500 text-white rounded-lg hover:bg-primary-600 transition-colors mt-4"
          >
            重试
          </button>
        </div>
      )
    }
    return this.props.children
  }
}

const TYPE_COLORS = {
  '调音': '#8b5cf6', '混剪': '#3b82f6', 'RAP': '#ef4444', '空耳': '#f59e0b',
  '鬼畜': '#ec4899', '恶搞': '#10b981', '影视': '#6366f1', '游戏': '#14b8a6',
  '素材': '#64748b', '教程': '#0ea5e9', '其他': '#94a3b8',
}

const TYPE_ICONS = {
  '调音': '🎵', '混剪': '✂️', 'RAP': '🎤', '空耳': '👂',
  '鬼畜': '👹', '恶搞': '😂', '影视': '🎬', '游戏': '🎮',
  '素材': '📦', '教程': '📚', '其他': '📌',
}

// ─── UP 分区标签配色（biliscope 式徽章，按名称哈希取色，鬼畜分区固定色）───
const KICHU_TAG_COLORS = { '鬼畜调教': '#ec4899', '音MAD': '#f43f5e', '人力VOCALOID': '#d946ef', '鬼畜剧场': '#ef4444', '鬼畜': '#ec4899' }
const TAG_PALETTE = ['#3b82f6', '#8b5cf6', '#ef4444', '#f59e0b', '#10b981', '#ec4899', '#06b6d4', '#f97316', '#6366f1', '#14b8a6']

// StatCard 迷你趋势线颜色（与卡片主题色一致）
const SPARK_COLORS = {
  blue: '#3b82f6', purple: '#8b5cf6', green: '#22c55e', orange: '#f97316',
}

// iOS 风格：触发后快速响应，末段以较长尾巴柔和停稳，不产生机械匀速感。
const IOS_MORPH_EASE = [0.32, 0.72, 0, 1]
const IOS_SETTLE_EASE = [0.22, 1, 0.36, 1]

function badgeColor(name) {
  if (KICHU_TAG_COLORS[name]) return KICHU_TAG_COLORS[name]
  let h = 0
  for (const c of name) h = (h * 31 + c.charCodeAt(0)) % 997
  return TAG_PALETTE[h % TAG_PALETTE.length]
}

function UpTrendsInner({ formatNumber, isAdmin, initialPublicAnalysis }) {
  const [phase, setPhase] = useState(initialPublicAnalysis ? 'ready' : 'checking') // checking | setup | loading | ready
  const [data, setData] = useState(initialPublicAnalysis || null)           // current analysis result
  const [history, setHistory] = useState([])        // historical batches for charts
  const [error, setError] = useState(null)
  const [warning, setWarning] = useState(null)
  const pollTimer = useRef(null)
  const pollGeneration = useRef(0)
  const activeTask = useRef(null)
  const mounted = useRef(false)
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      pollGeneration.current += 1
      clearTimeout(pollTimer.current)
    }
  }, [])
  const [view, setView] = useState('analysis')      // analysis | list
  const [refreshing, setRefreshing] = useState(false)
  const [contentTypeLimit, setContentTypeLimit] = useState(10)
  const [progress, setProgress] = useState(null)  // { current, total, current_up, eta_seconds }
  const [calendarTimeline, setCalendarTimeline] = useState([])  // 最近60个自然日（含零值日期）
  const [publishHabits, setPublishHabits] = useState(null)      // { hourly: [], weekly: [], meta: {} }
  const [followerGrowth, setFollowerGrowth] = useState([])       // 涨粉榜（up_obs 粉丝时序）
  const [hotGrowth, setHotGrowth] = useState([])                 // 高增速视频榜（video_obs_snapshot 跨批次播放增速）

  // ─── Size Morph 展开态：同排互斥 + Esc / 空白关闭 ───
  const [expandedCard, setExpandedCard] = useState(null)
  const onToggleCard = useCallback((key) => {
    setExpandedCard((cur) => (cur === key ? null : key))
  }, [])
  // Esc 关闭 + 点击卡片外空白关闭
  useEffect(() => {
    if (!expandedCard) return
    const onKey = (e) => { if (e.key === 'Escape') setExpandedCard(null) }
    // capture 阶段在 window 上监听会先于 overlay 的 stopPropagation 执行，
    // 必须显式排除展开卡片内部（含图表/列表）的点击，否则点图表看数据会被误关
    const onClick = (e) => {
      const t = e.target
      if (t && typeof t.closest === 'function' && t.closest('[data-stat-overlay]')) return
      setExpandedCard(null)
    }
    // 下一帧挂监听：避免"触发展开的那次 click 冒泡到 window"立即被关闭
    let t1 = setTimeout(() => {
      window.addEventListener('keydown', onKey)
      window.addEventListener('mousedown', onClick, true)
    }, 0)
    return () => {
      clearTimeout(t1)
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('mousedown', onClick, true)
    }
  }, [expandedCard])

  // ─── 访客申请 / 站长审核（公网多用户 · 方案C）───
  const [showRequestModal, setShowRequestModal] = useState(false) // 访客提交追踪申请
  const [showAdminModal, setShowAdminModal] = useState(false)     // 站长审核（仅管理员）

  // ─── Fetch publish habits (hourly/weekly aggregation) ───
  useEffect(() => {
    let cancelled = false
    api.getPublishHabits(180)
      .then((res) => { if (!cancelled && res.success) setPublishHabits(res.data || null) })
      .catch(() => {})
    return () => { cancelled = true }
  }, [history])

  // ─── Fetch follower growth ranking (latest batch vs window-start batch) ───
  useEffect(() => {
    let cancelled = false
    api.getFollowerGrowth(7, 10)
      .then((res) => { if (!cancelled && res.success) setFollowerGrowth(res.data || []) })
      .catch(() => {})
    return () => { cancelled = true }
  }, [history])

  // ─── Fetch hot growth videos (跨批次播放量增速最快的视频) ───
  useEffect(() => {
    let cancelled = false
    api.getUpTrendsHotGrowth(14, 10)
      .then((res) => { if (!cancelled && res.success) setHotGrowth(res.data || []) })
      .catch(() => {})
    return () => { cancelled = true }
  }, [history])

  // ─── 最近 60 个自然日：日历为唯一主数据源，零投稿日期由后端补齐 ───
  const loadCalendarTimeline = useCallback(async () => {
    const res = await api.getCalendarRecent(60)
    if (res?.success) setCalendarTimeline(res.data || [])
  }, [])
  useEffect(() => {
    loadCalendarTimeline()
    const timer = setInterval(loadCalendarTimeline, 60_000)
    return () => clearInterval(timer)
  }, [loadCalendarTimeline])

  // One live polling generation; reloads/unmounts cannot revive old timers.
  const pollProgress = useCallback((taskId) => {
    clearTimeout(pollTimer.current)
    const generation = ++pollGeneration.current
    activeTask.current = taskId
    setRefreshing(true)
    setError(null)
    setWarning(null)
    setProgress({ current: 0, total: 0, current_up: '等待 Worker 执行', eta_seconds: 0 })
    let failures = 0
    const current = () => mounted.current && pollGeneration.current === generation
    const stop = (message, terminal = false) => {
      if (!current()) return
      clearTimeout(pollTimer.current)
      if (terminal) activeTask.current = null
      setRefreshing(false)
      setProgress(null)
      setPhase('ready')
      if (message) setError(message)
    }
    const poll = async () => {
      if (!current()) return
      try {
        const res = await api.upTrendsProgress(taskId)
        if (!current()) return
        if (!res.success) {
          if (res.code === 'task_not_found') {
            stop(res.message || '任务不存在', true)
            return
          }
          throw new Error(res.message || '任务进度暂不可用')
        }
        const p = res.data
        setProgress(p)
        if (p.done) {
          if (p.status === 'failed') {
            stop(p.error?.message || (typeof p.error === 'string' ? p.error : '分析失败'), true)
            return
          }
          const analysisRes = await api.upTrendsAnalysis()
          if (!current()) return
          if (!analysisRes.success || !analysisRes.data) throw new Error('观测已保存，但暂时无法读取结果')
          setData(analysisRes.data)
          if (p.status === 'partial') {
            setWarning(p.warnings?.[0]?.message || p.error?.message || '观测已保存，后续任务未完成')
          }
          // A history read failure must not undo a successful core result.
          try {
            const histRes = await api.upTrendsHistory()
            if (current() && histRes.success) setHistory(histRes.data.batches || [])
          } catch { /* retain last usable history */ }
          stop(null, true)
          return
        }
        if (p.worker_unavailable) {
          stop('Worker 暂不可用，任务已保留在队列中，请稍后重新连接')
          return
        }
        failures = 0
        pollTimer.current = setTimeout(poll, 800)
      } catch (e) {
        if (!current()) return
        failures += 1
        if (failures >= 3) {
          stop('连接中断，已暂停查询：' + (e.message || '请稍后重新连接'))
          return
        }
        pollTimer.current = setTimeout(poll, 1000 * (2 ** (failures - 1)))
      }
    }
    poll()
  }, [])

  const initCheck = useCallback(async () => {
    clearTimeout(pollTimer.current)
    const generation = ++pollGeneration.current
    const current = () => mounted.current && pollGeneration.current === generation
    if (!initialPublicAnalysis) setPhase('checking')
    setError(null)
    try {
      const check = await api.upTrendsCheck()
      if (!current()) return
      if (check.success === false) throw new Error(check.message || '配置检查失败')
      if (!check.has_list) {
        setPhase(initialPublicAnalysis ? 'ready' : 'setup')
        return
      }
      activeTask.current = check.active_task_id || null
      if (!initialPublicAnalysis) setPhase('loading')
      const analysisRes = await api.upTrendsAnalysis()
      if (!current()) return
      if (analysisRes.success && analysisRes.data) setData(analysisRes.data)
      else if (!initialPublicAnalysis) setData(null)
      setPhase('ready')
      try {
        const histRes = await api.upTrendsHistory()
        if (current() && histRes.success) setHistory(histRes.data.batches || [])
      } catch { /* existing analysis remains usable */ }
      if (current() && activeTask.current) pollProgress(activeTask.current)
    } catch (e) {
      if (!current()) return
      setError(e.message)
      setPhase('ready')
      if (activeTask.current) pollProgress(activeTask.current)
    }
  }, [pollProgress, initialPublicAnalysis])

  useEffect(() => { initCheck() }, [initCheck])

  const startRefreshTask = useCallback(async () => {
    clearTimeout(pollTimer.current)
    const generation = ++pollGeneration.current
    const current = () => mounted.current && pollGeneration.current === generation
    setRefreshing(true)
    setError(null)
    setWarning(null)
    setProgress({ current: 0, total: 0, current_up: '正在提交任务...', eta_seconds: 0 })
    try {
      const res = await api.upTrendsRefresh()
      if (!current()) return
      if (res.task_id && (res.success || res.busy)) {
        pollProgress(res.task_id)
        return
      }
      setError(res.message || '启动分析失败')
    } catch (e) {
      if (!current()) return
      setError(e.message || '启动分析失败')
    }
    if (current()) {
      setRefreshing(false)
      setProgress(null)
      setPhase('ready')
    }
  }, [pollProgress])

  const handleRefresh = () => startRefreshTask()
  const handleReconnect = () => activeTask.current ? pollProgress(activeTask.current) : initCheck()
  const handleSetupComplete = () => {
    setPhase('loading')
    startRefreshTask()
  }

  // ─── Helpers ───
  const formatDate = (timestamp) => {
    if (!timestamp) return '未知'
    const d = new Date(timestamp * 1000)
    const now = new Date()
    const diff = (now - d) / 1000
    if (diff < 3600) return `${Math.floor(diff / 60)}分钟前`
    if (diff < 86400) return `${Math.floor(diff / 3600)}小时前`
    if (diff < 86400 * 7) return `${Math.floor(diff / 86400)}天前`
    return d.toLocaleDateString('zh-CN')
  }

  // ─── Format ETA ───
  const formatEta = (seconds) => {
    if (!seconds || seconds <= 0) return '计算中...'
    const m = Math.floor(seconds / 60)
    const s = seconds % 60
    if (m > 0) return `约 ${m} 分 ${s} 秒`
    return `约 ${s} 秒`
  }

  // ─── Extract analysis data (must be before early returns — hooks order invariant) ───
  const analysisResult = data || {}
  const analysis = analysisResult.analysis || {}
  const upTrendsList = analysisResult.up_details || data?.up_trends || []
  const summary = analysis.summary || {}
  const narrative = buildUpTrendsNarrative(summary, formatNumber)

  // ─── 汇总卡片趋势与变化率：基于历史批次（最近一次分析 vs 上一次） ───
  const validHist = useMemo(
    () => history.filter(s => s.analysis?.summary && s.analysis.summary.total_ups > 0),
    [history]
  )
  const prevSummary = validHist.length >= 2 ? validHist[validHist.length - 2].analysis.summary : null
  // 近 7 天窗口：趋势序列（预览+展开）统一裁剪到最近 7 天，与卡片标题"近7天"口径一致
  const recentHist = useMemo(() => {
    const cutoff = Date.now() / 1000 - 7 * 24 * 3600
    return validHist.filter(s => (s.created_at || 0) >= cutoff)
  }, [validHist])
  // 池口径标记：pool_summary 落库后批次带 pool_* 键；老批次只有 up_obs 聚合的 total_*
  const hasPool = (s) => !!(s && 'pool_total_views' in s)
  // 迁移窗口期口径不一致（当前批次有 pool_* 而上一批没有，或反之）：
  // 全量池数值系统性大于 up_obs 采样，直接对比会制造虚假大涨/大跌，delta 置 null
  const poolMixed = hasPool(summary) !== hasPool(prevSummary)
  // 趋势序列：总量字段优先视频池口径 pool_*（后端 pool_summary 落库），老批次无 pool 时回退 up_obs 聚合；
  // 口径切换批次数值置 null 断线（connectNulls 默认 false），避免跨口径直线失真
  const trendSeries = useMemo(() => {
    const seriesOf = (field, fallback) =>
      recentHist.map((s, i) => {
        const sm = s.analysis.summary
        const prevSm = i > 0 ? recentHist[i - 1].analysis.summary : null
        const mixed = hasPool(sm) !== hasPool(prevSm)
        return {
          ts: s.created_at,
          date: formatDate(s.created_at),
          value: mixed ? null : (sm[field] ?? sm[fallback] ?? 0),
        }
      })
    return {
      ups: recentHist.map(s => ({ ts: s.created_at, date: formatDate(s.created_at), value: s.analysis.summary.total_ups || 0 })),
      videos: seriesOf('pool_total_videos', 'total_videos'),
      views: seriesOf('pool_total_views', 'total_views'),
      avg: seriesOf('pool_avg_views_per_video', 'avg_views_per_video'),
    }
  }, [recentHist])
  const pctChange = (cur, prev) => {
    if (prev === null || prev === undefined) return null
    if (prev === 0) return cur === 0 ? 0 : null
    return ((cur - prev) / prev) * 100
  }
  const absChange = (cur, prev) => {
    if (prev === null || prev === undefined) return null
    return cur - prev
  }
  const keywordCloud = analysis.keyword_cloud || []
  const contentTypes = analysis.content_types || []
  const timeline = analysis.timeline || []
  const hotVideos = analysis.hot_videos || []
  // 优先 play_ranking，fallback 到 active_ranking
  const playRanking = analysis.play_ranking || analysis.active_ranking || []
  const creatorRanking = analysis.creator_ranking || []

  // 日历数据完整时不允许低覆盖率的批次 timeline 覆盖；失败时才回退旧数据。
  const displayTimeline = useMemo(() => {
    if (calendarTimeline.length > 0) return calendarTimeline
    return timeline
  }, [calendarTimeline, timeline])

  const maxTypeCount = Math.max(...contentTypes.map(t => t.count), 1)

  // ─── 发布习惯 option：小时发布量柱状图 + 平均播放折线（双轴）──
  const publishHabitOption = useMemo(() => {
    const hourly = publishHabits?.hourly || []
    if (!hourly.length) return null
    const hours = hourly.map((h) => `${String(h.hour).padStart(2, '0')}时`)
    const counts = hourly.map((h) => h.count)
    const avgs = hourly.map((h) => h.avg_views)
    const maxAvg = Math.max(...avgs, 1)
    return {
      tooltip: {
        trigger: 'axis',
        backgroundColor: 'rgba(255,255,255,0.96)',
        borderColor: '#e2e8f0',
        textStyle: { fontSize: 11, color: '#334155' },
        formatter: (params) => {
          const i = params[0].dataIndex
          return `<div style="font-size:11px;color:#64748b;margin-bottom:4px">${hours[i]}（北京时间）</div>
            <div style="display:flex;align-items:center;gap:8px;line-height:18px">
              <span style="display:inline-block;width:8px;height:8px;background:#0ea5e9;border-radius:50%"></span>
              <span>发布</span><span style="margin-left:auto;font-weight:600">${counts[i]} 个</span>
            </div>
            <div style="display:flex;align-items:center;gap:8px;line-height:18px">
              <span style="display:inline-block;width:8px;height:8px;background:#f59e0b;border-radius:50%"></span>
              <span>平均播放</span><span style="margin-left:auto;font-weight:600">${formatNumber(avgs[i])}</span>
            </div>`
        },
      },
      legend: { show: false },
      grid: { top: 24, left: 40, right: 64, bottom: 24 },
      xAxis: {
        type: 'category',
        data: hours,
        axisLine: { lineStyle: { color: '#e2e8f0' } },
        axisTick: { show: false },
        axisLabel: { fontSize: 10, color: '#94a3b8', interval: 1 },
      },
      yAxis: [
        {
          type: 'value', name: '发布数', nameTextStyle: { fontSize: 10, color: '#94a3b8' },
          axisLabel: { fontSize: 10, color: '#94a3b8' },
          splitLine: { lineStyle: { color: '#f1f5f9' } },
        },
        {
          type: 'value', name: '平均播放', nameTextStyle: { fontSize: 10, color: '#94a3b8' },
          axisLabel: { fontSize: 10, color: '#94a3b8', formatter: (v) => formatNumber(v) },
          splitLine: { show: false },
        },
      ],
      series: [
        {
          name: '发布数', type: 'bar', data: counts,
          itemStyle: { color: '#0ea5e9', borderRadius: [2, 2, 0, 0] },
          barMaxWidth: 14,
        },
        {
          name: '平均播放', type: 'line', yAxisIndex: 1, data: avgs, smooth: true,
          itemStyle: { color: '#f59e0b' },
          lineStyle: { width: 2, color: '#f59e0b' },
          symbolSize: 4,
          // 平均播放超过最大值一半的小时标注数值（突出高效果时段）
          label: {
            show: true, position: 'top', fontSize: 9, color: '#f59e0b',
            formatter: (p) => (avgs[p.dataIndex] >= maxAvg * 0.6 ? formatNumber(avgs[p.dataIndex]) : ''),
          },
        },
      ],
    }
  }, [publishHabits])

  // ─── 近期发布趋势 option：60 天竖向柱状图（柱顶数值 + 每 7 天一个日期标签）──
  const timelineOption = useMemo(() => {
    if (displayTimeline.length === 0) return null
    return {
      grid: { left: 36, right: 12, top: 20, bottom: 20 },
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        backgroundColor: 'rgba(255,255,255,0.96)',
        borderColor: '#e2e8f0',
        textStyle: { fontSize: 11, color: '#334155' },
        formatter: (params) => {
          const t = displayTimeline[params[0].dataIndex]
          return `<div style="font-size:11px;color:#64748b;margin-bottom:4px">${t.date}</div>
            <div style="color:#16a34a;font-weight:600">${t.count} 个视频</div>
            <div style="color:#64748b">${formatNumber(t.views)} 播放</div>`
        },
      },
      xAxis: {
        type: 'category',
        data: displayTimeline.map(t => t.date),
        axisLabel: {
          fontSize: 9,
          color: '#cbd5e1',
          // 每 7 天显示一个日期标签（与原实现一致），最后一个必显示
          interval: (idx) => idx % 7 === 0 || idx === displayTimeline.length - 1,
        },
        axisLine: { lineStyle: { color: '#e2e8f0' } },
        axisTick: { show: false },
      },
      yAxis: {
        type: 'value',
        minInterval: 1,
        axisLabel: { fontSize: 9, color: '#94a3b8' },
        // 去掉横向网格线，保持清爽
        splitLine: { show: false },
      },
      series: [{
        type: 'bar',
        data: displayTimeline.map(t => t.count),
        barWidth: 8,
        itemStyle: {
          borderRadius: [2, 2, 0, 0],
          color: {
            type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: '#34d399' },
              { offset: 1, color: '#4ade80' },
            ],
          },
        },
        label: {
          show: true,
          position: 'top',
          distance: 2,
          fontSize: 9,
          color: '#64748b',
          formatter: (p) => (p.value > 0 ? p.value : ''),
        },
        // 标签自动去重：横向压缩柱子变密时重叠标签自动隐藏
        labelLayout: { hideOverlap: true },
      }],
    }
  }, [displayTimeline, formatNumber])

  // ─── 排行榜 ECharts option（统一走 EChart 公共组件）──────────────
  // 播放量排行榜：横向柱 + 蓝紫渐变 + 自适应数值标签 + 奖牌/名次前缀
  const playRankOption = useMemo(() => {
    if (playRanking.length === 0) return null
    const items = playRanking.slice(0, 10)
    const reversed = [...items].reverse() // ECharts category 自底向上 → 第1名在顶部
    const rankMap = new Map(items.map((u, i) => [u.name, { ...u, rank: i + 1 }]))
    const maxViews = Math.max(...items.map(u => u.total_recent_views || 0), 1)
    // 小于最长柱 18% 时，柱体通常容不下“1.2万”这类完整标签。
    // 为每个数据项独立指定位置和颜色：长柱白字内置，短柱深色外置。
    const barData = reversed.map((u) => {
      const value = u.total_recent_views || 0
      const placeOutside = value / maxViews < 0.18
      return {
        value,
        label: {
          position: placeOutside ? 'right' : 'insideRight',
          distance: placeOutside ? 6 : 4,
          color: placeOutside ? '#6366f1' : '#fff',
        },
      }
    })
    return {
      grid: { left: 8, right: 44, top: 8, bottom: 20, containLabel: true },
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        backgroundColor: 'rgba(255,255,255,0.96)',
        borderColor: '#e2e8f0',
        textStyle: { fontSize: 11, color: '#334155' },
        formatter: (params) => {
          const u = rankMap.get(params[0].name)
          if (!u) return ''
          const kichuLine = u.kichu_video_count > 0
            ? `<div style="color:#ec4899">鬼畜视频: ${u.kichu_video_count} 部</div>`
            : ''
          return `<div style="font-size:12px;font-weight:700;color:#334155;margin-bottom:4px">${u.name}</div>
            <div style="color:#64748b">近7天播放: <b>${formatNumber(u.total_recent_views)}</b></div>
            ${kichuLine}`
        },
      },
      xAxis: {
        type: 'value',
        axisLabel: { fontSize: 9, color: '#94a3b8', formatter: (v) => v >= 10000 ? (v / 10000).toFixed(1) + '万' : v },
        splitLine: { lineStyle: { color: '#f1f5f9' } },
      },
      yAxis: {
        type: 'category',
        data: reversed.map(u => u.name),
        axisLabel: {
          fontSize: 11,
          color: '#475569',
          formatter: (name) => {
            const u = rankMap.get(name)
            if (!u) return name
            return `${u.rank <= 3 ? ['🥇', '🥈', '🥉'][u.rank - 1] : `${u.rank}.`} ${name}`
          },
        },
        axisLine: { show: false },
        axisTick: { show: false },
      },
      series: [{
        type: 'bar',
        data: barData,
        barWidth: 14,
        itemStyle: {
          borderRadius: 3,
          color: {
            type: 'linear', x: 0, y: 0, x2: 1, y2: 0,
            colorStops: [
              { offset: 0, color: '#60a5fa' },
              { offset: 1, color: '#a78bfa' },
            ],
          },
        },
        label: {
          show: true,
          distance: 4,
          color: '#fff',
          fontSize: 10,
          fontWeight: 700,
          formatter: (p) => formatNumber(p.value),
        },
        // 极端窗口宽度下仍避免相邻标签互相覆盖
        labelLayout: { hideOverlap: true },
      }],
    }
  }, [playRanking, formatNumber])

  // UP主活跃度排行：横向柱 + 绿渐变 + 柱内白字数量
  const creatorRankOption = useMemo(() => {
    if (creatorRanking.length === 0) return null
    const items = creatorRanking.slice(0, 10)
    const reversed = [...items].reverse()
    const rankMap = new Map(items.map((u, i) => [u.name, { ...u, rank: i + 1 }]))
    return {
      grid: { left: 8, right: 44, top: 8, bottom: 20, containLabel: true },
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        backgroundColor: 'rgba(255,255,255,0.96)',
        borderColor: '#e2e8f0',
        textStyle: { fontSize: 11, color: '#334155' },
        formatter: (params) => {
          const u = rankMap.get(params[0].name)
          if (!u) return ''
          let lastPub = '—'
          if (u.latest_pub_date) {
            const daysAgo = Math.floor((Date.now() / 1000 - u.latest_pub_date) / 86400)
            lastPub = daysAgo === 0 ? '今天' : daysAgo === 1 ? '昨天' : `${daysAgo}天前`
          }
          return `<div style="font-size:12px;font-weight:700;color:#334155;margin-bottom:4px">${u.name}</div>
            <div style="color:#64748b">近7天发布: <b>${u.recent_video_count} 部</b></div>
            <div style="color:#64748b">最近发布: ${lastPub}</div>`
        },
      },
      xAxis: {
        type: 'value',
        minInterval: 1,
        axisLabel: { fontSize: 9, color: '#94a3b8' },
        splitLine: { lineStyle: { color: '#f1f5f9' } },
      },
      yAxis: {
        type: 'category',
        data: reversed.map(u => u.name),
        axisLabel: {
          fontSize: 11,
          color: '#475569',
          formatter: (name) => {
            const u = rankMap.get(name)
            if (!u) return name
            return `${u.rank <= 3 ? ['🥇', '🥈', '🥉'][u.rank - 1] : `${u.rank}.`} ${name}`
          },
        },
        axisLine: { show: false },
        axisTick: { show: false },
      },
      series: [{
        type: 'bar',
        data: reversed.map(u => u.recent_video_count || 0),
        barWidth: 14,
        itemStyle: {
          borderRadius: 3,
          color: {
            type: 'linear', x: 0, y: 0, x2: 1, y2: 0,
            colorStops: [
              { offset: 0, color: '#4ade80' },
              { offset: 1, color: '#34d399' },
            ],
          },
        },
        label: {
          show: true,
          position: 'insideRight',
          distance: 4,
          color: '#fff',
          fontSize: 10,
          fontWeight: 700,
          formatter: (p) => `${p.value}部`,
        },
        // 标签自动去重：极端压缩时重叠标签自动隐藏
        labelLayout: { hideOverlap: true },
      }],
    }
  }, [creatorRanking])

  // ─── 涨粉榜 option：横向柱 + 涨绿跌红（最新批次 vs 窗口起点批次）───
  const followerGrowthOption = useMemo(() => {
    if (followerGrowth.length === 0) return null
    const items = followerGrowth.slice(0, 10)
    const reversed = [...items].reverse()
    const rankMap = new Map(items.map((u, i) => [u.name, { ...u, rank: i + 1 }]))
    return {
      grid: { left: 8, right: 44, top: 8, bottom: 20, containLabel: true },
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        backgroundColor: 'rgba(255,255,255,0.96)',
        borderColor: '#e2e8f0',
        textStyle: { fontSize: 11, color: '#334155' },
        formatter: (params) => {
          const u = rankMap.get(params[0].name)
          if (!u) return ''
          const sign = u.growth >= 0 ? '+' : ''
          return `<div style="font-size:12px;font-weight:700;color:#334155;margin-bottom:4px">${u.name}</div>
            <div style="color:#64748b">粉丝 ${formatNumber(u.follower_before)} → ${formatNumber(u.follower_now)}</div>
            <div style="color:${u.growth >= 0 ? '#16a34a' : '#dc2626'};font-weight:600">${sign}${formatNumber(u.growth)}（${sign}${u.growth_rate}%）</div>`
        },
      },
      xAxis: {
        type: 'value',
        axisLabel: { fontSize: 9, color: '#94a3b8', formatter: (v) => v >= 10000 ? (v / 10000).toFixed(1) + '万' : v },
        splitLine: { lineStyle: { color: '#f1f5f9' } },
      },
      yAxis: {
        type: 'category',
        data: reversed.map(u => u.name),
        axisLabel: {
          fontSize: 11,
          color: '#475569',
          formatter: (name) => {
            const u = rankMap.get(name)
            if (!u) return name
            return `${u.rank <= 3 ? ['🥇', '🥈', '🥉'][u.rank - 1] : `${u.rank}.`} ${name}`
          },
        },
        axisLine: { show: false },
        axisTick: { show: false },
      },
      series: [{
        type: 'bar',
        data: reversed.map(u => u.growth),
        barWidth: 14,
        itemStyle: {
          borderRadius: 3,
          // 涨粉为正 → 绿色渐变；掉粉为负 → 红色
          color: (params) => {
            if (params.value >= 0) {
              return {
                type: 'linear', x: 0, y: 0, x2: 1, y2: 0,
                colorStops: [
                  { offset: 0, color: '#4ade80' },
                  { offset: 1, color: '#16a34a' },
                ],
              }
            }
            return {
              type: 'linear', x: 0, y: 0, x2: 1, y2: 0,
              colorStops: [
                { offset: 0, color: '#f87171' },
                { offset: 1, color: '#dc2626' },
              ],
            }
          },
        },
        label: {
          show: true,
          position: 'insideRight',
          distance: 4,
          color: '#fff',
          fontSize: 10,
          fontWeight: 700,
          formatter: (p) => `${p.value >= 0 ? '+' : ''}${formatNumber(p.value)}`,
        },
        // 标签自动去重：极端压缩时重叠标签自动隐藏
        labelLayout: { hideOverlap: true },
      }],
    }
  }, [followerGrowth, formatNumber])

  // ─── UP 分区标签（biliscope 式）：进列表视图时异步分批拉取，缓存到组件 state ───
  const [upCards, setUpCards] = useState({})        // mid → card（含 video_types）
  const [cardLoading, setCardLoading] = useState({}) // mid → true
  const upCardsRef = useRef({})
  const cardLoadingRef = useRef({})

  // 真实口径统计：up_card 翻页全量里近7天视频的播放量（消除分析任务"5条采样+联合投稿平分"失真）。
  // 返回 { views, avg }；卡片未加载 / 字段缺失时返回 null（前端回退 up_obs 口径）。
  const monthStats = useCallback((mid) => {
    const c = upCards[mid]
    if (!c || typeof c.last_7d_views !== 'number') return null
    // count=0（近7天确实没发视频）：avg 无意义置 null，前端显示 '—'，
    // 不回退 up_obs 采样均值，避免与"近7天发布 0"同屏口径混杂
    if (!c.last_7d_count) return { views: c.last_7d_views, avg: null }
    return { views: c.last_7d_views, avg: Math.round(c.last_7d_views / c.last_7d_count) }
  }, [upCards])

  useEffect(() => {
    if (view !== 'list') return
    const ups = upTrendsList.length > 0 ? upTrendsList : (data?.up_trends || [])
    const pending = ups
      .map(u => u.mid)
      .filter(mid => !upCardsRef.current[mid] && !cardLoadingRef.current[mid])
    if (pending.length === 0) return
    const run = async () => {
      // 并发 3 一批 + 300ms 间隔，避免 30 个 UP 同时翻页触发 B站 限流
      for (let i = 0; i < pending.length; i += 3) {
        const batch = pending.slice(i, i + 3)
        await Promise.all(batch.map(async (mid) => {
          cardLoadingRef.current[mid] = true
          setCardLoading(prev => ({ ...prev, [mid]: true }))
          const res = await api.getUpCard(mid)
          if (res.success && res.data) {
            upCardsRef.current[mid] = res.data
            setUpCards({ ...upCardsRef.current })
          }
          delete cardLoadingRef.current[mid]
          setCardLoading(prev => { const n = { ...prev }; delete n[mid]; return n })
        }))
        if (i + 3 < pending.length) {
          await new Promise(r => setTimeout(r, 300))
        }
      }
    }
    run()
  }, [view, upTrendsList, data])

  // ─── Phase: checking ───
  if (phase === 'checking') {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="w-8 h-8 border-4 border-primary-500 border-t-transparent rounded-full animate-spin" />
        <span className="ml-3 text-slate-500">正在检查UP主动态配置...</span>
      </div>
    )
  }

  // ─── Phase: setup ───
  if (phase === 'setup') {
    return (
      <div className="max-w-3xl mx-auto">
        <h2 className="text-xl font-bold mb-3">UP主动态</h2>
        <p className="text-sm text-slate-500 mb-4">观测尚未配置，管理员可在开发者后台的“UP主观测”中维护名单。</p>
        <button className="rounded-lg bg-primary-500 text-white px-4 py-2 mb-4" onClick={() => setShowRequestModal(true)}>申请观测</button>
        <ObservationRoster />
        {showRequestModal && <UpRequestModal onClose={() => setShowRequestModal(false)} />}
      </div>
    )
  }

  // ─── Phase: loading / refreshing with progress ───
  if (phase === 'loading' || (refreshing && progress)) {
    const p = progress || { current: 0, total: 0, current_up: '准备中...', eta_seconds: 0 }
    const pct = p.total > 0 ? Math.round((p.current / p.total) * 100) : 0
    return (
      <div className="max-w-lg mx-auto py-16">
        <div className="bg-white rounded-xl border border-slate-200 p-6">
          <h3 className="text-lg font-bold text-slate-800 mb-1">
            {refreshing ? '正在刷新UP主动态' : '正在分析UP主动态'}
          </h3>
          <p className="text-sm text-slate-500 mb-4">
            已分析 {p.current}/{p.total} 个UP主 · {formatEta(p.eta_seconds)}剩余
          </p>

          {/* Progress bar */}
          <div className="w-full h-3 bg-slate-100 rounded-full overflow-hidden mb-3">
            <div
              className="h-full bg-gradient-to-r from-blue-500 to-purple-500 rounded-full transition-all duration-500"
              style={{ width: `${Math.max(pct, 2)}%` }}
            />
          </div>

          {/* Current UP主 */}
          <div className="flex items-center gap-3 text-sm">
            <div className="w-5 h-5 border-2 border-primary-500 border-t-transparent rounded-full animate-spin flex-shrink-0" />
            <span className="text-slate-600 truncate">
              {p.status === 'finalizing' ? '观测已保存，正在提交日历任务：' : p.status === 'queued' ? '任务状态：' : '正在分析：'} <strong className="text-slate-800">{p.current_up}</strong>
            </span>
          </div>
        </div>
      </div>
    )
  }

  // ─── Phase: ready ───
  return (
    <div>
      {/* 访客申请追踪 / 站长审核弹窗（公网多用户） */}
      {showRequestModal && <UpRequestModal initialTab={showRequestModal === 'roster' ? 'roster' : 'search'} onClose={() => setShowRequestModal(false)} />}

      {/* Narrative header */}
      <section className="relative mb-5 overflow-hidden rounded-2xl border border-slate-200 bg-white px-5 py-5 shadow-sm md:px-7 md:py-6">
        <div aria-hidden="true" className="absolute -right-16 -top-20 h-48 w-48 rounded-full bg-primary-50/70 blur-3xl" />
        <div className="relative flex flex-wrap items-start justify-between gap-5">
          <div className="min-w-0 max-w-3xl">
            <p className="mb-2 flex items-center gap-2 text-[11px] font-bold tracking-[0.14em] text-emerald-700">
              <span className="h-2 w-2 rounded-full bg-emerald-500 shadow-[0_0_0_4px_rgba(16,185,129,0.12)]" />
              {narrative.eyebrow}
            </p>
            <h1 id="up-trends-title" className="flex items-center gap-2 text-2xl font-bold tracking-tight text-slate-900 md:text-[28px]">
              <Users className="text-primary-500" size={27} />
              <span>UP主动态</span>
            </h1>
            <p className="mt-4 text-lg font-semibold leading-snug text-slate-800 md:text-xl">{narrative.headline}</p>
            <p className="mt-1.5 text-sm text-slate-500">{narrative.detail}</p>
          </div>
          <div className="flex flex-wrap items-center justify-end gap-2">
          {/* View toggle */}
          <div className="flex rounded-xl border border-slate-200/90 bg-white/90 p-0.5 shadow-sm">
            <button
              onClick={() => setView('analysis')}
              className={`px-3 py-1.5 text-sm font-medium rounded-lg transition-colors ${view === 'analysis' ? 'bg-primary-500 text-white' : 'text-slate-600 hover:bg-slate-50'}`}
            >
              <BarChart3 size={15} className="inline mr-1" />分析面板
            </button>
            <button
              onClick={() => setView('list')}
              className={`px-3 py-1.5 text-sm font-medium rounded-lg transition-colors ${view === 'list' ? 'bg-primary-500 text-white' : 'text-slate-600 hover:bg-slate-50'}`}
            >
              <List size={15} className="inline mr-1" />UP主列表
            </button>
          </div>
          {/* Action buttons */}
          {/* 申请追踪：访客与管理员均可提交（站长后台审核） */}
          <button
            onClick={() => setShowRequestModal(true)}
            className="flex items-center gap-2 px-3 py-2 bg-primary-500 text-white rounded-lg hover:bg-primary-600 transition-colors text-sm font-medium shadow-sm"
          >
            <UserPlus size={16} />申请观测
          </button>
          <button
            onClick={() => setShowRequestModal('roster')}
            className="flex items-center gap-2 rounded-xl border border-slate-200 bg-white/90 px-3 py-2 text-sm font-medium text-slate-600 shadow-sm transition-colors hover:border-primary-200 hover:bg-primary-50 hover:text-primary-600"
          >
            <Eye size={16} />当前观测名单
          </button>
          {isAdmin && <button
            onClick={handleRefresh}
            disabled={refreshing}
            className="flex items-center gap-2 rounded-xl border border-slate-200 bg-white/90 px-3 py-2 text-sm font-medium text-slate-600 shadow-sm transition-colors hover:bg-slate-50 disabled:opacity-50"
          >
            <RefreshCw size={16} className={refreshing ? 'animate-spin' : ''} />刷新动态
          </button>}
          {/* 管理员专属：名单管理 + 申请审核 */}
          </div>
        </div>
        {analysisResult.created_at && (
          <div className="relative mt-5 flex flex-wrap items-center gap-2 border-t border-slate-200/70 pt-4 text-xs text-slate-500">
            <span className="rounded-full border border-emerald-100 bg-emerald-50/80 px-3 py-1.5 font-medium text-emerald-700">数据在线</span>
            <span className="rounded-full border border-slate-200/80 bg-white/70 px-3 py-1.5">更新于 {formatDate(analysisResult.created_at)}</span>
            <span className="rounded-full border border-slate-200/80 bg-white/70 px-3 py-1.5">观测 {analysisResult.tracked_up_count || summary.total_ups || 0} 位 UP 主</span>
          </div>
        )}
      </section>

      {/* Error banner */}
      {error && (
        <div className="mb-4 px-4 py-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-600">
          {error}
          {activeTask.current
            ? <button onClick={handleReconnect} className="ml-3 underline hover:text-red-700">重新连接</button>
            : isAdmin && <button onClick={handleRefresh} className="ml-3 underline hover:text-red-700">重试</button>}
        </div>
      )}
      {warning && (
        <div role="status" className="mb-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          {warning}
        </div>
      )}

      {/* No data yet */}
      {!data && !refreshing && (
        <div className="flex flex-col items-center justify-center py-20 bg-white rounded-xl border border-slate-200">
          <Sparkles className="text-slate-300 mb-4" size={48} />
          <p className="text-slate-500 mb-2">名单已配置，暂无分析数据</p>
          <button onClick={handleRefresh} className="px-4 py-2 bg-primary-500 text-white rounded-lg hover:bg-primary-600 transition-colors mt-2">
            立即刷新
          </button>
        </div>
      )}

      {/* ============ Analysis view ============ */}
      {data && view === 'analysis' && (
        <div className="space-y-6">
          {/* 1. Summary cards — Size Morph（左上锚点向右下扩展宽高，参考子康兄 Size Morph 概念稿）
               * 收起态：紧凑指标卡 + 迷你趋势
               * 展开态：主数值保持左上锚点放大突出；向右下生长的空间里出现 ECharts 趋势大图 + 细分表现辅助面板
               * 同排互斥（expandedCard 单张）；Esc / 外部点击 / ✕ 按钮 三种关闭方式
               */}
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            <StatCard
              statKey="ups"
              expanded={expandedCard === 'ups'}
              onToggle={onToggleCard}
              icon={Users} label="追踪UP主" value={summary.total_ups || 0} suffix="人" color="blue"
              delta={absChange(summary.total_ups || 0, prevSummary?.total_ups)} deltaUnit="人"
              trendData={trendSeries.ups}
              buildOption={() => buildTrendOption(trendSeries.ups, SPARK_COLORS.blue, '追踪UP主', (v) => v + ' 人')}
              breakdown={topActiveBreakdown(summary, creatorRanking, prevSummary, 'total_ups')}
            />
            <StatCard
              statKey="videos"
              expanded={expandedCard === 'videos'}
              onToggle={onToggleCard}
              icon={Video} label="近期视频总数" value={summary.pool_total_videos ?? summary.total_videos ?? 0} suffix="个" color="purple"
              delta={poolMixed ? null : absChange(summary.pool_total_videos ?? summary.total_videos ?? 0, prevSummary?.pool_total_videos ?? prevSummary?.total_videos ?? 0)} deltaUnit="个"
              trendData={trendSeries.videos}
              buildOption={() => buildTrendOption(trendSeries.videos, SPARK_COLORS.purple, '近期视频总数', (v) => formatNumber(v) + ' 个')}
              breakdown={contentTypesBreakdown(contentTypes, summary, prevSummary, 'pool_total_videos', 'total_videos')}
            />
            <StatCard
              statKey="views"
              expanded={expandedCard === 'views'}
              onToggle={onToggleCard}
              icon={Eye} label="近7天总播放" value={formatNumber(summary.pool_total_views ?? summary.total_views ?? 0)} color="green"
              delta={poolMixed ? null : pctChange(summary.pool_total_views ?? summary.total_views ?? 0, prevSummary?.pool_total_views ?? prevSummary?.total_views ?? 0)} deltaUnit="%"
              trendData={trendSeries.views}
              buildOption={() => buildTrendOption(trendSeries.views, SPARK_COLORS.green, '近7天总播放', (v) => formatNumber(v))}
              breakdown={typeViewsBreakdown(contentTypes, summary, prevSummary)}
            />
            <StatCard
              statKey="avg"
              expanded={expandedCard === 'avg'}
              onToggle={onToggleCard}
              icon={TrendingUp} label="近7天平均播放" value={formatNumber(summary.pool_avg_views_per_video ?? summary.avg_views_per_video ?? 0)} color="orange"
              delta={poolMixed ? null : pctChange(summary.pool_avg_views_per_video ?? summary.avg_views_per_video ?? 0, prevSummary?.pool_avg_views_per_video ?? prevSummary?.avg_views_per_video ?? 0)} deltaUnit="%"
              trendData={trendSeries.avg}
              buildOption={() => buildTrendOption(trendSeries.avg, SPARK_COLORS.orange, '近7天平均播放', (v) => formatNumber(v))}
              breakdown={publishHabitBreakdown(publishHabits)}
            />
          </div>

          {/* 2. 成果区：什么火了（播放量排行 + 排行变化 + 热门TOP10） */}
          <div className="space-y-4">
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <div className="bg-white rounded-xl border border-slate-200 p-5">
                <h3 className="text-lg font-bold text-slate-800 mb-4 flex items-center gap-2">
                  <Trophy className="text-yellow-400" size={20} /> 播放量排行榜
                </h3>
                {playRanking.length === 0 ? (
                  <p className="text-sm text-slate-400 text-center py-4">暂无数据</p>
                ) : (
                  <EChart option={playRankOption} height={Math.min(playRanking.length, 10) * 36} />
                )}
              </div>
              <PlayRankingChangeCard batches={history} />
            </div>

            {/* 热门视频 TOP 10（横向通栏网格卡片） */}
            <div className="bg-white rounded-xl border border-slate-200 p-5">
              <h3 className="text-lg font-bold text-slate-800 mb-4 flex items-center gap-2">
                <Flame className="text-orange-400" size={20} /> 热门视频 TOP 10
              </h3>
              {hotVideos.length === 0 ? (
                <p className="text-sm text-slate-400 text-center py-4">暂无数据</p>
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-3">
                  {hotVideos.map((v, i) => {
                    // 处理联合投稿作者：最多显示 2 个，多余的用 +N 省略
                    const authors = v._coauthors || (v.up_name ? [{ name: v.up_name, mid: v.up_mid }] : [])
                    const showAuthors = authors.slice(0, 2)
                    const extraCount = Math.max(0, authors.length - 2)
                    const authorStr = showAuthors.map(a => a.name).join(' / ') + (extraCount > 0 ? ` 等${extraCount + 2}人` : '')
                    const rank = i + 1
                    const isTop3 = rank <= 3
                    // B站图床直连会被浏览器 ORB/CORS 拦截，统一走本地代理
                    const coverUrl = v.cover ? `/api/proxy/image?url=${encodeURIComponent(v.cover)}` : ''
                    return (
                      <a key={`${v.bvid || ''}-${i}`} href={v.url || `https://www.bilibili.com/video/${v.bvid}`} target="_blank" rel="noopener noreferrer"
                        className="group bg-slate-50 rounded-xl overflow-hidden hover:shadow-md transition-shadow flex flex-col">
                        {/* 封面 + 排名角标 */}
                        <div className="relative aspect-video bg-slate-200">
                          {coverUrl && (
                            <img
                              src={coverUrl} alt={v.title} loading="lazy"
                              className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
                              onError={(e) => { e.target.style.display = 'none' }}
                            />
                          )}
                          <span className={`absolute top-1.5 left-1.5 min-w-6 h-6 px-1.5 rounded-md flex items-center justify-center text-xs font-bold shadow-sm ${
                            isTop3
                              ? 'bg-gradient-to-br from-red-500 to-orange-500 text-white'
                              : 'bg-black/60 text-white backdrop-blur-sm'
                          }`}>{rank}</span>
                        </div>
                        {/* 文字信息 */}
                        <div className="p-2.5 flex flex-col gap-1 flex-1">
                          <p className="text-xs font-medium text-slate-700 line-clamp-2 leading-snug group-hover:text-primary-500" title={v.title}>
                            {v.title}
                          </p>
                          <p className="text-[10px] text-slate-400 truncate" title={authorStr}>{authorStr}</p>
                          <div className="flex items-center justify-between text-[10px] text-slate-400 mt-auto pt-0.5">
                            <span className="text-orange-500 font-semibold">{formatNumber(v.views)}播放</span>
                            <span>{formatDate(v.pub_date)}</span>
                          </div>
                        </div>
                      </a>
                    )
                  })}
                </div>
              )}
            </div>

            {/* 高增速视频 TOP 10（横向列表 + 增速条，区别于热门TOP10 网格卡片） */}
            <div className="bg-white rounded-xl border border-slate-200 p-5">
              <h3 className="text-lg font-bold text-slate-800 mb-1 flex items-center gap-2">
                <Rocket className="text-primary-500" size={20} /> 高增速视频 TOP 10
                <span className="text-xs font-normal text-slate-400 ml-1">最近分析间隔 · 按每小时新增播放</span>
              </h3>
              <p className="text-xs text-slate-400 mb-3">播放量增速最快的视频——新作发布即猛涨是选题风向标，增速条越长代表近期涨得越猛</p>
              {hotGrowth.length === 0 ? (
                <p className="text-sm text-slate-400 text-center py-4">暂无增速数据（需至少 2 个分析批次）</p>
              ) : (
                <div className="space-y-1">
                  {hotGrowth.map((v, i) => {
                    const rank = i + 1
                    const isTop3 = rank <= 3
                    // 联合投稿作者：最多显示 2 个，多余的用 +N 省略（与热门TOP10 一致）
                    const authors = v._coauthors || (v.up_name ? [{ name: v.up_name, mid: v.up_mid }] : [])
                    const showAuthors = authors.slice(0, 2)
                    const extraCount = Math.max(0, authors.length - 2)
                    const authorStr = showAuthors.map(a => a.name).join(' / ') + (extraCount > 0 ? ` 等${extraCount + 2}人` : '')
                    const coverUrl = v.cover ? `/api/proxy/image?url=${encodeURIComponent(v.cover)}` : ''
                    // 增速条长度：相对榜首速度的比例（最低 3% 保证可见）
                    const speedPct = Math.max((v.speed / (hotGrowth[0]?.speed || 1)) * 100, 3)
                    const rateStr = v.growth_rate != null ? `+${v.growth_rate}%` : ''
                    return (
                      <a key={v.bvid} href={v.url} target="_blank" rel="noopener noreferrer"
                        className="group flex items-center gap-3 p-2 rounded-lg hover:bg-slate-50 transition-colors">
                        <span className={`w-6 h-6 shrink-0 rounded-md flex items-center justify-center text-xs font-bold ${
                          isTop3
                            ? 'bg-gradient-to-br from-primary-500 to-bili-dark text-white'
                            : 'bg-slate-100 text-slate-500'
                        }`}>{rank}</span>
                        <div className="w-16 h-10 rounded-md bg-slate-100 flex-shrink-0 overflow-hidden relative">
                          {coverUrl && (
                            <img src={coverUrl} alt={v.title} loading="lazy"
                              className="w-full h-full object-cover"
                              onError={(e) => { e.target.style.display = 'none' }} />
                          )}
                        </div>
                        <div className="flex-1 min-w-0">
                          <p className="text-xs font-medium text-slate-700 line-clamp-1 leading-snug group-hover:text-primary-500 transition-colors" title={v.title}>
                            {v.title}
                          </p>
                          <p className="text-[10px] text-slate-400 truncate" title={authorStr}>{authorStr}</p>
                        </div>
                        <div className="w-44 shrink-0">
                          <div className="flex items-baseline justify-between gap-2">
                            <span className="text-xs font-bold text-green-600 tabular-nums">+{formatNumber(v.growth_views)}</span>
                            <span className="text-[10px] text-slate-400 tabular-nums"
                              title={`近 ${v.hours} 小时新增 ${formatNumber(v.growth_views)} 播放`}>
                              {rateStr}{rateStr && ' · '}{formatNumber(v.speed)}/时
                            </span>
                          </div>
                          <div className="h-1.5 bg-slate-100 rounded-full mt-1 overflow-hidden">
                            <div className="h-full rounded-full bg-gradient-to-r from-green-400 to-emerald-500 transition-all duration-500"
                              style={{ width: `${speedPct}%` }} />
                          </div>
                        </div>
                      </a>
                    )
                  })}
                </div>
              )}
            </div>
          </div>

          {/* 3. 发布区：什么时候发的（60天趋势 + 全年日历） */}
          <div className="space-y-4">
            <div className="bg-white rounded-xl border border-slate-200 p-5">
              <h3 className="text-lg font-bold text-slate-800 mb-4 flex items-center gap-2">
                <Calendar className="text-green-400" size={20} /> 近期发布趋势
                <span className="text-xs font-normal text-slate-400 ml-1">最近60天</span>
              </h3>
              {displayTimeline.length > 0 ? (
                <EChart option={timelineOption} height={128} />
              ) : (
                <p className="text-sm text-slate-400 text-center py-8">暂无近期发布数据</p>
              )}
            </div>
            <PublishCalendarCard
              batches={history}
              isAdmin={isAdmin}
              onCalendarUpdated={loadCalendarTimeline}
            />

            <div className="bg-white rounded-xl border border-slate-200 p-5">
              <h3 className="text-lg font-bold text-slate-800 mb-1 flex items-center gap-2">
                <Clock className="text-teal-500" size={20} /> 发布习惯
                <span className="text-xs font-normal text-slate-400 ml-1">近180天 · 按北京时间</span>
              </h3>
              <div className="mb-3 flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
                <p className="text-xs text-slate-400">各小时发布量（蓝柱）与平均播放（橙线）——发布多≠效果好，结合平均播放判断最佳发稿时段</p>
                {publishHabits?.meta?.fetched_at && (
                  <p className="shrink-0 text-[11px] text-slate-400">
                    {publishHabits.meta.video_count || 0} 个样本 · 数据更新于 {new Date(publishHabits.meta.fetched_at * 1000).toLocaleString('zh-CN', { hour12: false })}
                  </p>
                )}
              </div>
              {publishHabitOption ? (
                <>
                  <div
                    aria-label="发布习惯图例"
                    className="mb-1 flex h-4 items-center justify-end gap-6 pr-3 text-[11px] text-slate-500"
                  >
                    <span className="inline-flex items-center gap-2 whitespace-nowrap">
                      <span className="h-2.5 w-2.5 rounded-[2px] bg-sky-500" />
                      发布数
                    </span>
                    <span className="inline-flex items-center gap-2 whitespace-nowrap">
                      <span className="relative inline-block h-2.5 w-5 shrink-0">
                        <span className="absolute left-0 right-0 top-1/2 h-0.5 -translate-y-1/2 bg-amber-500" />
                        <span className="absolute left-1/2 top-1/2 h-2 w-2 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-amber-500 bg-white" />
                      </span>
                      平均播放
                    </span>
                  </div>
                  <EChart option={publishHabitOption} height={200} />
                </>
              ) : (
                <p className="text-sm text-slate-400 text-center py-8">暂无发布习惯数据</p>
              )}
            </div>
          </div>

          {/* 4. 内容区：发了什么（词云 + 类型分布 + 鬼畜占比） */}
          <div className="space-y-4">
            <KeywordCloudCard keywordCloud={keywordCloud} />

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <div className="bg-white rounded-xl border border-slate-200 p-5">
                <h3 className="text-lg font-bold text-slate-800 mb-4 flex items-center gap-2">
                  <BarChart3 className="text-purple-400" size={20} /> 内容类型分布
                </h3>
                <div className="relative">
                  <div className="space-y-2.5">
                    {contentTypes.length === 0 ? (
                      <span className="text-sm text-slate-400">暂无数据</span>
                    ) : (
                      contentTypes.slice(0, contentTypeLimit).map((ct, i) => {
                        const pct = (ct.count / maxTypeCount) * 100
                        const color = TYPE_COLORS[ct.type] || '#94a3b8'
                        return (
                          <div key={`${ct.type}-${i}`} className="flex items-center gap-3">
                            <div className="flex-shrink-0 w-32 text-sm text-slate-600 flex items-center gap-1 overflow-hidden">
                              <span>{TYPE_ICONS[ct.type] || '📌'}</span>
                              <span className="truncate" title={ct.type}>{ct.type}</span>
                            </div>
                            <div className="flex-1 h-5 bg-slate-50 rounded-md overflow-hidden relative">
                              <div className="h-full rounded-md bg-gradient-to-r from-blue-400 to-purple-400 transition-all duration-500 flex items-center justify-end px-2"
                                style={{ width: `${Math.max(pct, 5)}%` }}>
                                <span className="text-white text-[10px] font-bold">{ct.count}</span>
                              </div>
                            </div>
                          </div>
                        )
                      })
                    )}
                  </div>
                  {contentTypes.length > 10 && contentTypeLimit < contentTypes.length && (
                    <div className="absolute bottom-0 left-0 right-0 h-10 bg-gradient-to-t from-white to-transparent pointer-events-none" />
                  )}
                </div>
                {contentTypes.length > 10 && (
                  <div className="mt-2 flex justify-end">
                    <button
                      onClick={() => setContentTypeLimit(prev =>
                        prev >= contentTypes.length ? 10 : Math.min(prev + 10, contentTypes.length)
                      )}
                      className="text-xs flex items-center gap-0.5 text-slate-400 hover:text-slate-600 transition-colors"
                    >
                      {contentTypeLimit >= contentTypes.length ? (
                        <>
                          收起 <ChevronUp size={13} />
                        </>
                      ) : (
                        <>
                          展开更多 <ChevronDown size={13} />
                        </>
                      )}
                    </button>
                  </div>
                )}
              </div>
              <KichuRatioCard batches={history} />
            </div>
          </div>

          {/* 5. 活跃区：谁在活跃（活跃UP变化 + 活跃度排行） */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <ActiveUpCard batches={history} />
            <div className="bg-white rounded-xl border border-slate-200 p-5">
              <h3 className="text-lg font-bold text-slate-800 mb-4 flex items-center gap-2">
                <Activity className="text-green-500" size={20} /> UP主活跃度排行
              </h3>
              <p className="text-xs text-slate-400 mb-3">按近7天发布数量排序，体现创作积极性</p>
              {creatorRanking.length === 0 ? (
                <p className="text-sm text-slate-400 text-center py-4">暂无数据</p>
              ) : (
                <EChart option={creatorRankOption} height={Math.min(creatorRanking.length, 10) * 36} />
              )}
            </div>
          </div>

          {/* 6. 涨粉榜：谁在涨（最新批次 vs 7天前批次的粉丝变化） */}
          <div className="bg-white rounded-xl border border-slate-200 p-5">
            <h3 className="text-lg font-bold text-slate-800 mb-1 flex items-center gap-2">
              <TrendingUp className="text-emerald-500" size={20} /> 涨粉榜
              <span className="text-xs font-normal text-slate-400 ml-1">近7天 · 最新批次 vs 窗口起点批次</span>
            </h3>
            <p className="text-xs text-slate-400 mb-3">粉丝增长最快的UP主——涨粉与活跃/播放未必同步，是内容策略的独立信号</p>
            {followerGrowthOption ? (
              <EChart option={followerGrowthOption} height={Math.min(followerGrowth.length, 10) * 36} />
            ) : (
              <p className="text-sm text-slate-400 text-center py-4">暂无涨粉数据（需至少 2 个观测批次）</p>
            )}
          </div>

        </div>
      )}

      {/* ============ UP主 List view ============ */}
      {data && view === 'list' && (
        <div className="space-y-4">
          {(upTrendsList.length > 0 ? upTrendsList : (data?.up_trends || [])).map((up, idx) => (
            <div key={up.mid} className="bg-white rounded-xl border border-slate-200 overflow-hidden">
              <div className="p-4 flex items-center gap-4 border-b border-slate-100">
                <div className="relative">
                  <img
                    src={up.face ? `/api/proxy/image?url=${encodeURIComponent(up.face)}` : ''}
                    alt={up.name} className="w-12 h-12 rounded-full object-cover bg-slate-100"
                    onError={(e) => { e.target.src = 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="%23cbd5e1"><circle cx="12" cy="8" r="4"/><path d="M12 14c-4 0-8 2-8 6v2h16v-2c0-4-4-6-8-6z"/></svg>' }}
                  />
                  {up.kichu_video_count > 0 && (
                    <div className="absolute -bottom-1 -right-1 bg-primary-500 text-white text-[10px] px-1.5 py-0.5 rounded-full font-bold">鬼畜</div>
                  )}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <a href={`https://space.bilibili.com/${up.mid}`} target="_blank" rel="noopener noreferrer" className="font-bold text-slate-800 hover:text-primary-500 transition-colors">
                      {up.name}
                    </a>
                    <ExternalLink size={12} className="text-slate-300" />
                  </div>
                  <div className="flex items-center gap-3 text-xs text-slate-500 mt-0.5">
                    <span>粉丝 {formatNumber(up.follower_count)}</span>
                    {/* 总投稿数来自 up_card（接口真实总数），近7天发布数优先取 up_card 全量计数，卡片加载完成前用 up_obs 口径兜底 */}
                    {upCards[up.mid]?.video_count != null && (
                      <span title="该UP主全部投稿数（接口总数）">总投稿 {formatNumber(upCards[up.mid].video_count)}</span>
                    )}
                    {(() => {
                      // 近7天播放 / 平均：卡片加载后切到 up_card 全量真实口径（含联合投稿不按合作者平分），
                      // 卡片未加载时回退 up_obs 的"5条采样+平分"口径（与历史排行/总结卡一致）
                      const ms = monthStats(up.mid)
                      return (
                        <>
                          <span title="近7天内发布的视频数">近7天发布 {upCards[up.mid]?.last_7d_count ?? up.recent_video_count ?? 0}</span>
                          {ms ? (
                            <>
                              <span title="近7天真实总播放（up_card 翻页全量，联合投稿不按合作者平分）">近7天播放 {formatNumber(ms.views)}</span>
                              <span title="近7天真实总播放 ÷ 近7天发布数（up_card 全量口径）">平均 {formatNumber(ms.avg)} 播放</span>
                            </>
                          ) : (
                            <span title="近7天发布视频的总播放 ÷ 近7天发布视频数（卡片加载前为观测采样口径）">平均 {formatNumber(up.avg_views)} 播放</span>
                          )}
                        </>
                      )
                    })()}
                  </div>
                  {/* 分区标签（biliscope 式：投稿量 top3 分区，点击跳 B站分区页） */}
                  <div className="flex items-center gap-1.5 mt-1.5 flex-wrap">
                    {(upCards[up.mid]?.video_types || []).map(t => (
                      <a
                        key={t.tid}
                        href={`https://www.bilibili.com/v/${t.link}`}
                        target="_blank" rel="noopener noreferrer"
                        className="text-[10px] px-1.5 py-0.5 rounded font-medium hover:opacity-80 transition-opacity"
                        style={{ backgroundColor: badgeColor(t.name) + '1A', color: badgeColor(t.name) }}
                        title={`投稿 ${t.count} 个视频`}
                      >
                        {t.name}
                      </a>
                    ))}
                    {cardLoading[up.mid] && (
                      <span className="text-[10px] text-slate-300 animate-pulse">加载标签中...</span>
                    )}
                  </div>
                </div>
                <div className="text-right text-xs text-slate-400">
                  {up.latest_pub_date > 0 && <div>最近更新: {formatDate(up.latest_pub_date)}</div>}
                </div>
              </div>

              {up.sign && (
                <div className="px-4 py-2 text-xs text-slate-500 bg-slate-50 border-b border-slate-100 truncate">{up.sign}</div>
              )}

              {up.latest_videos && up.latest_videos.length > 0 ? (
                <div className="p-3">
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                    {up.latest_videos.slice(0, 4).map((video, i) => (
                      <a key={`${video.bvid || ''}-${i}`} href={video.url || `https://www.bilibili.com/video/${video.bvid}`} target="_blank" rel="noopener noreferrer"
                        className="flex gap-3 p-2 rounded-lg hover:bg-slate-50 transition-colors group">
                        <div className="w-20 h-12 bg-slate-100 rounded-md flex-shrink-0 overflow-hidden relative">
                          {video.cover && <img src={`/api/proxy/image?url=${encodeURIComponent(video.cover)}`} alt={video.title} className="w-full h-full object-cover" />}
                          {video.duration > 0 && (
                            <span className="absolute bottom-0 right-0 bg-black/70 text-white text-[10px] px-1 rounded-sm">
                              {Math.floor(video.duration / 60)}:{String(video.duration % 60).padStart(2, '0')}
                            </span>
                          )}
                        </div>
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-medium text-slate-700 line-clamp-2 group-hover:text-primary-500 transition-colors">{video.title}</p>
                          <div className="flex items-center gap-2 mt-1 text-xs text-slate-400">
                            <span>{formatNumber(video.views)} 播放</span>
                            <span>·</span>
                            <span>{formatDate(video.pub_date)}</span>
                            {video.trend_label && (
                              <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${
                                video.trend_label === '爆发期' ? 'bg-red-50 text-red-600' :
                                video.trend_label === '上升期' ? 'bg-orange-50 text-orange-600' :
                                'bg-slate-50 text-slate-500'
                              }`}>{video.trend_label}</span>
                            )}
                          </div>
                        </div>
                      </a>
                    ))}
                  </div>
                </div>
              ) : (
                <div className="p-4 text-center text-sm text-slate-400">暂无近期视频</div>
              )}
            </div>
          ))}
        </div>
      )}

    </div>
  )
}

// ─── Export with error boundary ───
export default function UpTrends(props) {
  return (
    <UpTrendsErrorBoundary>
      <UpTrendsInner {...props} />
    </UpTrendsErrorBoundary>
  )
}

// ─── KeywordCloudCard sub-component ───
const CLOUD_COLORS_ARR = ['#ef4444', '#f97316', '#f59e0b', '#22c55e', '#14b8a6', '#06b6d4', '#3b82f6', '#6366f1', '#8b5cf6', '#a855f7', '#ec4899', '#eab308']

function KeywordCloudCard({ keywordCloud }) {
  const viewportRef = useRef(null)
  const containerRef = useRef(null)
  // 往下拉调整词云显示面积（最小=默认280px，最大=整个边框1:1）
  const { height: viewportH, startResize } = useResizableHeight(280, containerRef, viewportRef)

  // ── Spiral layout ──
  const { positions, bbox } = useMemo(() => {
    if (!keywordCloud || keywordCloud.length === 0) {
      return { positions: [], bbox: { w: 0, h: 0, minX: 0, minY: 0 } }
    }
    const sorted = [...keywordCloud].sort((a, b) => b.count - a.count)
    const maxC = Math.max(...sorted.map(k => k.count), 1)
    const getFontSize = (count) => {
      const ratio = Math.pow(count / maxC, 1.4)
      return 13 + ratio * 38  // 13–51px
    }
    return computeSpiralPositions(
      sorted.map(k => ({ word: k.text, count: k.count })),
      getFontSize,
    )
  }, [keywordCloud])

  const getOpacity = (count) => {
    if (!keywordCloud || keywordCloud.length === 0) return 1
    const maxC = Math.max(...keywordCloud.map(k => k.count), 1)
    return 0.55 + Math.pow(count / maxC, 1.2) * 0.45
  }

  const cloudW = bbox.w + 60
  const cloudH = bbox.h + 60
  const offX = -bbox.minX + 30
  const offY = -bbox.minY + 30

  // ── Zoom & pan state ──
  const [scale, setScale] = useState(0.5)
  const [offset, setOffset] = useState({ x: 0, y: 0 })
  const [dragging, setDragging] = useState(false)
  const dragStart = useRef(null)

  // Auto-fit scale (grid column ≈ 560px wide)
  // targetH 跟随 viewportH，往下拉扩大面积时词云自动放大填满新空间
  const autoScale = useMemo(() => {
    if (cloudW === 0) return 1
    const sW = (560 - 24) / cloudW
    const sH = (viewportH - 24) / cloudH
    return Math.min(sW, sH, 1)
  }, [cloudW, cloudH, viewportH])

  useEffect(() => {
    if (cloudW > 0) { setScale(autoScale); setOffset({ x: 0, y: 0 }) }
  }, [autoScale])

  const clampScale = (s) => Math.max(0.15, Math.min(3, s))
  const zoomIn = () => setScale(s => clampScale(s * 1.25))
  const zoomOut = () => setScale(s => clampScale(s / 1.25))
  const zoomReset = () => { setScale(autoScale); setOffset({ x: 0, y: 0 }) }

  // 用 ref 保存最新 scale，避免 useEffect 依赖 scale 导致反复绑定/解绑 wheel 监听器
  const scaleRef = useRef(scale)
  useEffect(() => { scaleRef.current = scale }, [scale])

  // 手动绑定非被动 wheel 监听器：React 的 onWheel 在 Chrome 中默认 passive，
  // e.preventDefault() 不生效会导致页面跟着滚动。必须用 passive:false 才能阻止。
  useEffect(() => {
    const el = viewportRef.current
    if (!el) return
    const onWheel = (e) => {
      e.preventDefault()
      const rect = el.getBoundingClientRect()
      const mx = e.clientX - rect.left
      const my = e.clientY - rect.top
      const cx = mx - rect.width / 2
      const cy = my - rect.height / 2
      const currentScale = scaleRef.current
      const factor = e.deltaY > 0 ? 0.9 : 1.1
      const newScale = clampScale(currentScale * factor)
      const ratio = newScale / currentScale
      setOffset(prev => ({ x: cx - ratio * (cx - prev.x), y: cy - ratio * (cy - prev.y) }))
      setScale(newScale)
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [])

  const handleMouseDown = useCallback((e) => {
    if (e.target.closest('[data-cloud-word]')) return
    e.preventDefault()
    setDragging(true)
    dragStart.current = { x: e.clientX - offset.x, y: e.clientY - offset.y }
  }, [offset])

  const handleMouseMove = useCallback((e) => {
    if (!dragging || !dragStart.current) return
    setOffset({ x: e.clientX - dragStart.current.x, y: e.clientY - dragStart.current.y })
  }, [dragging])

  const handleMouseUp = useCallback(() => { setDragging(false); dragStart.current = null }, [])

  // ── Empty state ──
  if (keywordCloud.length === 0) {
    return (
      <div className="bg-white rounded-xl border border-slate-200 p-5">
        <h3 className="text-lg font-bold text-slate-800 mb-4 flex items-center gap-2">
          <Cloud className="text-blue-400" size={20} /> 视频标题热词
        </h3>
        <div className="flex items-center justify-center min-h-[80px]">
          <span className="text-sm text-slate-400">暂无数据</span>
        </div>
      </div>
    )
  }

  const sorted = [...keywordCloud].sort((a, b) => b.count - a.count)

  return (
    <div ref={containerRef} className="bg-white rounded-xl border border-slate-200 overflow-hidden">
      {/* Header bar */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-slate-100">
        <h3 className="text-sm font-bold text-slate-800 flex items-center gap-2">
          <Cloud className="text-blue-400" size={16} /> 视频标题热词
        </h3>
        {/* Zoom controls */}
        <div className="flex items-center gap-0.5">
          <button onClick={zoomOut} title="缩小"
            className="p-1 rounded text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors"
          ><ZoomOut size={14} /></button>
          <span className="text-[10px] text-slate-400 w-10 text-center tabular-nums select-none">
            {Math.round(scale * 100)}%
          </span>
          <button onClick={zoomIn} title="放大"
            className="p-1 rounded text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors"
          ><ZoomIn size={14} /></button>
          <button onClick={zoomReset} title="重置"
            className="p-1 rounded text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors ml-0.5"
          ><RotateCcw size={13} /></button>
        </div>
      </div>

      {/* Viewport */}
      <div
        ref={viewportRef}
        className="relative overflow-hidden select-none"
        style={{
          height: `${viewportH}px`,
          cursor: dragging ? 'grabbing' : 'grab',
        }}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
      >
        <div style={{ position: 'absolute', left: '50%', top: '50%', width: 0, height: 0 }}>
          <div
            style={{
              position: 'absolute',
              width: `${cloudW}px`,
              height: `${cloudH}px`,
              transform: `translate(-50%, -50%) translate(${offset.x}px, ${offset.y}px) scale(${scale})`,
            }}
          >
            {sorted.map((kw, i) => {
              const pos = positions[i]
              if (!pos) return null
              const color = CLOUD_COLORS_ARR[i % CLOUD_COLORS_ARR.length]
              const opacity = getOpacity(kw.count)
              return (
                <span
                  key={i}
                  data-cloud-word={kw.text}
                  className="inline-block font-bold select-none cursor-default rounded px-1.5 py-0.5"
                  style={{
                    position: 'absolute',
                    left: `${offX + pos.x}px`,
                    top: `${offY + pos.y}px`,
                    transform: 'translate(-50%, -50%)',
                    fontSize: `${pos.fontSize}px`,
                    color,
                    opacity,
                    transition: 'opacity 150ms',
                    whiteSpace: 'nowrap',
                  }}
                  title={`${kw.text}: ${kw.count}次`}
                >
                  {kw.text}
                </span>
              )
            })}
          </div>
        </div>
      </div>

      {/* 往下拉调整词云面积 - 最小=默认280px，最大=整个边框1:1 */}
      <div
        className="group flex items-center justify-center h-2 cursor-row-resize bg-slate-50 hover:bg-slate-100 transition-colors border-t border-slate-100"
        onMouseDown={startResize}
        title="往下拖动可扩大词云显示面积"
      >
        <div className="w-10 h-0.5 bg-slate-300 group-hover:bg-primary-400 rounded-full transition-colors" />
      </div>
    </div>
  )
}

// ─── 汇总卡片展开态共用：趋势 ECharts option（4 张卡复用，避免重复构造代码）───
function buildTrendOption(data, color, title, yLabel = (v) => formatNumber(v)) {
  if (!data || data.length < 2) return null
  const values = data.map(d => d.value)
  const minV = Math.min(...values.filter(v => v !== null && !isNaN(v)))
  const maxV = Math.max(...values.filter(v => v !== null && !isNaN(v)))
  if (isNaN(minV) || isNaN(maxV)) return null
  const range = maxV - minV
  // 数据无变化或极窄范围（如追踪UP主恒定138）：以中心值 ±5% 作为图区范围，
  // 避免 min/max 接近时 ECharts 自动刻度留下大面积空白
  const flatRange = range < 2
  const ref = (minV + maxV) / 2
  const padAmt = flatRange
    ? Math.max(Math.abs(ref) * 0.05, 2)
    : Math.max(range * 0.15, 1)
  const wantMin = flatRange ? ref - padAmt : minV - padAmt
  const wantMax = flatRange ? ref + padAmt : maxV + padAmt
  // nice 刻度步长（1/2/5×10^k）：强制 min/max 时 ECharts 会把精确边界硬塞进刻度
  // 导致首尾刻度对挤（如 131,132 | 135 | 138 | 141 | 144,145）。
  // 这里把边界吸附到步长整数倍并显式设置 interval，保证刻度等距且为“好看”的数字
  const niceStep = (raw) => {
    if (!(raw > 0) || !isFinite(raw)) return 1
    const pow = Math.pow(10, Math.floor(Math.log10(raw)))
    const f = raw / pow
    return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * pow
  }
  const step = niceStep((wantMax - wantMin) / 5)
  const yMin = Math.floor(wantMin / step) * step
  const yMax = Math.ceil(wantMax / step) * step
  // X 轴标签：绝对时间短格式（MM-DD HH:mm），按数据量均匀抽稀，铺满整个横轴
  const fmtAxis = (ts) => {
    if (!ts) return ''
    const d = new Date(ts * 1000)
    const m = String(d.getMonth() + 1).padStart(2, '0')
    const day = String(d.getDate()).padStart(2, '0')
    const hh = String(d.getHours()).padStart(2, '0')
    const mm = String(d.getMinutes()).padStart(2, '0')
    return `${m}-${day} ${hh}:${mm}`
  }
  return {
    animation: true,
    animationDurationUpdate: 390,
    animationEasingUpdate: 'cubicOut',
    // 让 ECharts 按刻度文本的真实宽度留位，避免固定 46px 在“1.0万”这类
    // 短标签左侧浪费空间；右侧也略收紧，为细分面板留出更多呼吸感。
    grid: { left: 6, right: 10, top: 8, bottom: 4, containLabel: true },
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(255,255,255,0.96)',
      borderColor: '#e2e8f0',
      textStyle: { fontSize: 11, color: '#334155' },
      formatter: (params) => {
        const d = data[params[0].dataIndex]
        if (!d || d.value == null) return ''
        return `<div style="font-size:11px;color:#64748b;margin-bottom:4px">${d.date}</div>
          <div style="display:flex;align-items:center;gap:8px;line-height:18px">
            <span style="display:inline-block;width:8px;height:8px;background:${color};border-radius:50%"></span>
            <span>${title}</span>
            <span style="margin-left:12px;font-weight:600">${yLabel(d.value)}</span>
          </div>`
      },
    },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: data.map(d => fmtAxis(d.ts)),
      axisLabel: {
        fontSize: 9,
        color: '#94a3b8',
        margin: 6,
        interval: Math.max(1, Math.ceil(data.length / 6)),
        formatter: (v) => v.split(' ')[0],
      },
      axisLine: { lineStyle: { color: '#e2e8f0' } },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value',
      min: yMin,
      max: yMax,
      interval: step,
      axisLabel: {
        fontSize: 9,
        color: '#94a3b8',
        margin: 6,
        formatter: (v) => String(yLabel(v)).replace(/\s+(人|个)$/, '$1'),
      },
      splitLine: { lineStyle: { color: '#f1f5f9' } },
    },
    series: [{
      type: 'line',
      data: values,
      smooth: true,
      showSymbol: false,
      itemStyle: { color },
      lineStyle: { width: 2.2, color },
      areaStyle: {
        color: {
          type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [
            { offset: 0, color: color + '2e' },
            { offset: 1, color: 'rgba(255,255,255,0)' },
          ],
        },
      },
    }],
  }
}

// ─── 4 种卡片的"细分表现"辅助面板构造（统一返回 items/footHint/headline）───

// 追踪UP主 → 活跃UP主榜 TOP5（近7天投稿量 / 对应播放贡献）
function topActiveBreakdown(summary, creatorRanking, prevSummary, field) {
  const cur = summary?.[field] || 0
  const prev = prevSummary?.[field] || 0
  const head = creatorRanking?.[0]
  // 第一的基准度量：优先近7天播放，其次历史播放，最后用投稿量×1000兜底
  const headViews = head
    ? (head.total_recent_views ?? head.total_views ?? 0)
    : 0
  const headMetric = headViews || ((head?.recent_video_count || 0) * 1000) || 1
  const items = (creatorRanking || []).slice(0, 5).map((u, i) => {
    // API creator_ranking 字段：total_recent_views（近7天播放），fallback 到 legacy total_views
    const views = u.total_recent_views ?? u.total_views ?? 0
    // 投稿量（近7天）作为进度条基准——无播放数据时也能按投稿量显示比例
    const metric = views || (u.recent_video_count || 0) * 1000
    return {
      label: u.name || `UP ${i + 1}`,
      value: `${u.recent_video_count || 0} 部（${formatNumber(views)} 播放）`,
      barWidth: Math.min(100, (metric / Math.max(headMetric, 1)) * 100),
    }
  })
  const diff = cur - prev
  return {
    items: items.length ? items : [{ label: '暂无活跃UP主数据', value: '—', barWidth: 0 }],
    footHint: prev > 0 ? `较上次 ${diff >= 0 ? '+' : ''}${diff} 人（${((diff / prev) * 100).toFixed(1)}%）` : `当前共 ${cur} 个追踪UP主`,
    headline: '活跃TOP5（近7天投稿量）',
  }
}

// 近期视频总数 → 内容类型投稿占比 TOP5
function contentTypesBreakdown(contentTypes, summary, prevSummary, poolKey, legacyKey) {
  const cur = summary?.[poolKey] ?? summary?.[legacyKey] ?? 0
  const prev = prevSummary?.[poolKey] ?? prevSummary?.[legacyKey] ?? 0
  const total = Math.max(cur, 1)
  const items = (contentTypes || []).slice(0, 5).map((ct) => {
    const color = TYPE_COLORS[ct.type] || '#94a3b8'
    return {
      label: ct.type,
      value: `${ct.count} 部（${((ct.count / total) * 100).toFixed(0)}%）`,
      barWidth: Math.min(100, (ct.count / total) * 100),
      barColor: color,
    }
  })
  const diff = cur - prev
  return {
    items: items.length ? items : [{ label: '暂无类型数据', value: '—', barWidth: 0 }],
    footHint: prev > 0 ? `较上次 ${diff >= 0 ? '+' : ''}${diff} 部` : `当前池内 ${cur} 部`,
    headline: '内容类型 · 投稿占比 TOP5',
  }
}

// 近7天总播放 → 内容类型 × 播放贡献 TOP5（按投稿量 × 平均播放近似）
function typeViewsBreakdown(contentTypes, summary, prevSummary) {
  const cur = summary?.pool_total_views ?? summary?.total_views ?? 0
  const prev = prevSummary?.pool_total_views ?? prevSummary?.total_views ?? 0
  const avgPerVideo = cur / Math.max((summary?.pool_total_videos ?? summary?.total_videos ?? 0), 1)
  const typed = (contentTypes || []).map((ct) => ({
    type: ct.type,
    estimated: (ct.count || 0) * avgPerVideo,
    count: ct.count || 0,
  })).sort((a, b) => b.estimated - a.estimated).slice(0, 5)
  const totalEst = Math.max(typed.reduce((s, t) => s + t.estimated, 0), 1)
  const items = typed.map((t) => {
    const color = TYPE_COLORS[t.type] || '#94a3b8'
    return {
      label: t.type,
      value: `${formatNumber(t.estimated)}（${t.count} 部）`,
      barWidth: Math.min(100, (t.estimated / totalEst) * 100),
      barColor: color,
    }
  })
  const diff = cur - prev
  const pct = prev > 0 ? ((diff / prev) * 100).toFixed(1) : null
  return {
    items: items.length ? items : [{ label: '暂无播放数据', value: '—', barWidth: 0 }],
    footHint: prev > 0
      ? `较上次 ${diff >= 0 ? '+' : ''}${formatNumber(diff)}（${pct != null ? (diff >= 0 ? '+' : '') + pct + '%' : ''}）`
      : `当前总播放 ${formatNumber(cur)}`,
    headline: '播放贡献 · 类型 TOP5',
  }
}

// 近7天平均播放 → 发布习惯黄金时段（小时维度平均播放 TOP5）
function publishHabitBreakdown(publishHabits) {
  const hourly = publishHabits?.hourly || []
  const sorted = [...hourly].sort((a, b) => (b.avg_views || 0) - (a.avg_views || 0)).slice(0, 5)
  const maxAvg = Math.max(...sorted.map(h => h.avg_views || 0), 1)
  const items = sorted.map((h) => ({
    label: `${String(h.hour).padStart(2, '0')}:00 – ${String((h.hour + 1) % 24).padStart(2, '0')}:00`,
    value: `均播 ${formatNumber(h.avg_views || 0)} · 投稿 ${h.count || 0} 部`,
    barWidth: Math.min(100, ((h.avg_views || 0) / maxAvg) * 100),
    barColor: '#f97316',
  }))
  const best = sorted[0]
  return {
    items: items.length ? items : [{ label: '暂无发布习惯数据', value: '—', barWidth: 0 }],
    footHint: best ? `黄金时段：${String(best.hour).padStart(2, '0')}:00 平均播放最高` : '数据不足',
    headline: '高效果时段 · 平均播放 TOP5',
  }
}

// 展开折线收回时切换为与 MiniSparkLine 一致的无坐标轴视图。
// 数据、Y 轴范围和面积色仍沿用大图 option，因此线条能连续缩放到预览形态。
function compactTrendOption(option) {
  if (!option) return {}
  const hideAxis = (axis) => Array.isArray(axis)
    ? axis.map(item => ({ ...item, show: false }))
    : { ...(axis || {}), show: false }
  const series = (Array.isArray(option.series) ? option.series : [option.series])
    .filter(Boolean)
    .map(item => ({
      ...item,
      showSymbol: false,
      symbol: 'none',
      label: { ...(item.label || {}), show: false },
      lineStyle: { ...(item.lineStyle || {}), width: 1.5 },
    }))
  return {
    ...option,
    animationDuration: 0,
    animationDurationUpdate: 360,
    animationEasingUpdate: 'cubicOut',
    grid: { left: 4, right: 4, top: 4, bottom: 4, containLabel: false },
    tooltip: { ...(option.tooltip || {}), show: false },
    xAxis: hideAxis(option.xAxis),
    yAxis: hideAxis(option.yAxis),
    series,
  }
}

// ─── StatCard sub-component — Size Morph（左上锚点，向右下方向扩展宽高）───
// 设计参考：子康兄 Size Morph 概念稿 —— 锁定锚点 → 改变宽高 → 突出数值；
// 同排互斥：同页 expandedCard 仅一张；展开态用 fixed 覆盖层做"原地生长"，不挤压相邻卡片。
function StatCard({
  statKey, expanded, onToggle,
  icon: Icon, label, value, suffix, color, delta, deltaUnit = '%',
  trendData,
  buildOption,   // () => echarts option（延迟构造，仅展开时调用）
  breakdown,     // { items: [{label,value,barWidth%,barColor?}], footHint, headline }
}) {
  const cardRef = useRef(null)
  const [rect, setRect] = useState(null)   // {top,left,width,height} 收起态视口坐标
  // 关闭时不立即卸载浮层；等收回动画结束再卸载。重新展开会直接改写动画目标，
  // Framer Motion 会从当前帧反向运行，因此 opening / closing 可互相打断。
  const [overlayMounted, setOverlayMounted] = useState(false)
  // 浮层先用 compact 图表挂载一帧，再切到完整图表；这样 ECharts 能从
  // 预览折线连续过渡到带坐标轴的大图，而不是首次渲染就跳到展开态。
  const [detailOpen, setDetailOpen] = useState(false)
  const expandedRef = useRef(expanded)
  expandedRef.current = expanded

  useEffect(() => {
    let detailTimer = 0
    if (expanded && rect) {
      setOverlayMounted(true)
      setDetailOpen(false)
      // 约 4 帧的 compact 锚定让预览线先稳定出现；随后同一 ECharts
      // 实例更新为完整 option，折线会在外框 morph 期间完成尺寸和位移过渡。
      detailTimer = window.setTimeout(() => {
        if (expandedRef.current) setDetailOpen(true)
      }, 64)
    } else {
      setDetailOpen(false)
    }
    return () => window.clearTimeout(detailTimer)
  }, [expanded, Boolean(rect)])

  const VIEWPORT_MARGIN = 16
  // 宽高优先使用设计尺寸；小视口时保留安全边距，避免浮层本身被裁切。
  const viewportWidth = typeof window === 'undefined' ? 1280 : window.innerWidth
  const viewportHeight = typeof window === 'undefined' ? 720 : window.innerHeight
  const TARGET_W = Math.min(640, Math.max(280, viewportWidth - VIEWPORT_MARGIN * 2))
  const TARGET_H = Math.min(440, Math.max(260, viewportHeight - VIEWPORT_MARGIN * 2))

  // 持续记录卡片真实视口矩形（收起/展开都要测量，确保 expanded 切换瞬间 rect 已经有值，避免"闪一下消失再出现"）
  useEffect(() => {
    const measure = () => {
      if (!cardRef.current) return
      const r = cardRef.current.getBoundingClientRect()
      setRect({ top: r.top, left: r.left, width: r.width, height: r.height })
    }
    measure()
    // 初始测量后下一帧再确认一次（防图片/字体加载后卡片高度变化）
    const t = setTimeout(measure, 50)
    const onScrollOrResize = () => measure()
    window.addEventListener('resize', onScrollOrResize)
    window.addEventListener('scroll', onScrollOrResize, true)
    return () => {
      clearTimeout(t)
      window.removeEventListener('resize', onScrollOrResize)
      window.removeEventListener('scroll', onScrollOrResize, true)
    }
  }, [])

  const colors = {
    blue:   'from-blue-500 to-blue-600',
    purple: 'from-purple-500 to-purple-600',
    green:  'from-green-500 to-green-600',
    orange: 'from-orange-500 to-orange-600',
  }
  const accent = SPARK_COLORS[color] || '#3b82f6'
  const hasDelta = delta !== null && delta !== undefined && !isNaN(delta)
  const deltaUp = hasDelta && delta > 0
  const deltaFlat = hasDelta && Math.abs(delta) < 0.05

  // 先从收起卡的左上角开始 morph；若 640px 详情卡会越过视口边缘，
  // 则在生长期间同步平移到安全范围，保证四张卡的完整内容和关闭按钮都可见。
  const openX = rect ? rect.left : 0
  const openY = rect ? rect.top : 0
  const maxOpenX = Math.max(VIEWPORT_MARGIN, viewportWidth - TARGET_W - VIEWPORT_MARGIN)
  const maxOpenY = Math.max(VIEWPORT_MARGIN, viewportHeight - TARGET_H - VIEWPORT_MARGIN)
  const targetX = Math.min(Math.max(openX, VIEWPORT_MARGIN), maxOpenX)
  const targetY = Math.min(Math.max(openY, VIEWPORT_MARGIN), maxOpenY)

  // 折叠态样式：普通 div（无需 motion），展开层以 fixed 浮起覆盖在它上方；
  // 折叠卡始终显示 → 收回时展开层 scale 缩回、折叠卡自然显露，无空白/卡顿
  const staticCls = `bg-white rounded-xl border border-slate-200 p-4 flex flex-col cursor-pointer group select-none relative`

  // 收起态 / 展开态共用一套内容结构 → 视觉锚点"焊死"在左上角（图标 + 主数值位置完全对齐）
  const renderInner = (layoutVariant, isOpen = true) => {
    const isExp = layoutVariant === 'expanded'
    const fullTrendOption = isExp && buildOption ? (buildOption() || {}) : null
    return (
      <div className="relative flex flex-col h-full w-full">
        {/* ── 顶部：图标 + 变化徽章（双态结构一致）── */}
        <div className="flex items-start justify-between flex-shrink-0">
          <div className={`w-10 h-10 rounded-lg bg-gradient-to-br ${colors[color] || colors.blue} flex items-center justify-center shadow-sm flex-shrink-0`}>
            <Icon className="text-white" size={20} />
          </div>
          <motion.div
            className="flex items-center gap-1.5"
            animate={{ marginRight: isExp && isOpen ? 36 : 0 }}
            transition={{ duration: 0.3, ease: IOS_SETTLE_EASE }}
          >
            {hasDelta && (
              <span
                className={`flex items-center gap-0.5 text-xs font-semibold rounded-md px-1.5 py-0.5 ${
                  deltaFlat
                    ? 'text-slate-400 bg-slate-50'
                    : deltaUp
                      ? 'text-green-600 bg-green-50'
                      : 'text-red-500 bg-red-50'
                }`}
                title="较上次分析"
              >
                {deltaFlat ? (
                  '持平'
                ) : (
                  <>
                    {deltaUp ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
                    {Math.abs(delta).toFixed(1)}{deltaUnit}
                  </>
                )}
              </span>
            )}
            {isExp ? (
              <motion.button
                onClick={(e) => { e.stopPropagation(); onToggle(statKey) }}
                className="absolute top-0 right-0 w-7 h-7 flex items-center justify-center rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors"
                title="关闭 (Esc)"
                aria-hidden={!isOpen}
                tabIndex={isOpen ? 0 : -1}
                animate={{ opacity: isOpen ? 1 : 0, scale: isOpen ? 1 : 0.75 }}
                transition={{ duration: 0.18, ease: IOS_SETTLE_EASE }}
                style={{ pointerEvents: isOpen ? 'auto' : 'none' }}
              >
                <X size={16} />
              </motion.button>
            ) : null}
          </motion.div>
        </div>

        {/* ── 中部：主数值 + 标签（视觉锚点核心）──
             不再做独立 scale（此前 1.45/0.79 叠加造成"跳变"），改由外框 layoutId 共享布局
             做整体 morph：icon / 标题 / 标签 保持相对比例与左上锚点，随卡片尺寸位移动画一起展开/收回 */}
        <motion.div
          className="mt-2"
          animate={{ marginBottom: isExp && isOpen ? 20 : 0 }}
          transition={{ duration: 0.32, ease: IOS_SETTLE_EASE }}
        >
          <div className="font-bold text-slate-800 leading-tight text-2xl">
            {value}
            {suffix && (
              <span className="ml-1 text-slate-400 font-normal text-sm">{suffix}</span>
            )}
          </div>
          <div className="text-xs text-slate-500">{label}</div>
        </motion.div>

        {/* ── 下部：随扩展空间出现的数据（趋势大图 + 细分表现）──
             两阶段：容器 width/height 负责"长大"，本节内容 opacity 延迟淡入负责"出现"，
             避免卡片生长初期被硬塞进小盒子（图表挤出来 / ECharts 尺寸错乱）*/}
        {isExp ? (
          <motion.div
            initial={{ opacity: 0, marginTop: 8 }}
            animate={{
              opacity: isOpen ? 1 : 0,
              marginTop: isOpen ? 0 : 8,
            }}
            transition={{
              opacity: { delay: isOpen ? 0.12 : 0, duration: isOpen ? 0.28 : 0.16, ease: IOS_SETTLE_EASE },
              marginTop: { duration: 0.34, ease: IOS_SETTLE_EASE },
            }}
            className="flex flex-1 min-h-0"
          >
              {/* 左侧折线始终是同一个 EChart 实例。退出时它扩大 flex 占比、去掉边框和
                  内边距，并随外框一起移动缩小，最终落到收起态迷你折线的位置。 */}
              <motion.div
                data-stat-chart="true"
                data-stat-chart-state={isOpen ? 'expanded' : 'compact'}
                className="min-w-0 min-h-0 rounded-xl flex flex-col overflow-hidden"
                style={{ flexBasis: 0, borderStyle: 'solid', borderWidth: 1 }}
                initial={{ flexGrow: 1, padding: 0, marginRight: 0, borderColor: 'rgba(241,245,249,0)' }}
                animate={{
                  flexGrow: isOpen ? 3 : 1,
                  padding: isOpen ? 8 : 0,
                  marginRight: isOpen ? 24 : 0,
                  borderColor: isOpen ? '#f1f5f9' : 'rgba(241,245,249,0)',
                }}
                transition={{ duration: 0.34, ease: IOS_SETTLE_EASE }}
              >
                {fullTrendOption ? (
                  <EChart option={isOpen ? fullTrendOption : compactTrendOption(fullTrendOption)} fill />
                ) : (
                  <div className="flex items-center justify-center text-xs text-slate-500 h-full">数据不足</div>
                )}
              </motion.div>
            {/* 右侧细分表现：收回时宽度归零并淡出，不参与最终预览态。 */}
            <motion.div
              data-stat-breakdown="true"
              className="min-w-0 min-h-0 flex flex-col overflow-hidden"
              style={{ flexBasis: 0 }}
              initial={{ flexGrow: 2, opacity: 0, x: 10 }}
              animate={{
                flexGrow: isOpen ? 2 : 0,
                opacity: isOpen ? 1 : 0,
                x: isOpen ? 0 : 18,
              }}
              transition={{
                flexGrow: { duration: 0.34, ease: IOS_SETTLE_EASE },
                opacity: { duration: isOpen ? 0.26 : 0.16, delay: isOpen ? 0.12 : 0, ease: IOS_SETTLE_EASE },
                x: { duration: 0.3, ease: IOS_SETTLE_EASE },
              }}
            >
              <div className="flex items-center gap-1.5 mb-2 flex-shrink-0">
                <div className="w-1 h-4 rounded-full" style={{ background: accent }} />
                <div className="text-xs font-semibold text-slate-700">
                  {breakdown?.headline || '细分表现'}
                </div>
              </div>
              <div className="flex-1 min-h-0 overflow-y-auto space-y-1.5 pr-1">
                {(breakdown?.items || []).length === 0 && (
                  <div className="text-xs text-slate-400">暂无数据</div>
                )}
                {(breakdown?.items || []).map((it, idx) => (
                  <div key={idx}>
                    <div className="flex items-center justify-between text-[11px]">
                      <span className="text-slate-700 truncate max-w-[55%]">{it.label}</span>
                      <span className="text-slate-500 font-medium tabular-nums flex-shrink-0 ml-2">{it.value}</span>
                    </div>
                    <div className="h-1.5 bg-slate-100 rounded-full mt-1 overflow-hidden">
                      <motion.div
                        className="h-full rounded-full"
                        initial={{ width: '0%' }}
                        animate={{ width: `${Math.max(0, Math.min(100, it.barWidth || 0))}%` }}
                        transition={{ duration: 0.5, delay: 0.14 + idx * 0.055, ease: IOS_SETTLE_EASE }}
                        style={{ background: it.barColor || accent }}
                      />
                    </div>
                  </div>
                ))}
              </div>
              {breakdown?.footHint && (
                <div className="mt-2 pt-2 border-t border-slate-100 text-[11px] text-slate-500 flex items-center gap-1.5 flex-shrink-0">
                  <Minus size={12} className="text-slate-300" />
                  <span className="truncate">{breakdown.footHint}</span>
                </div>
              )}
            </motion.div>
          </motion.div>
        ) : (
          <div className="mt-2 flex-1 flex items-end relative min-h-[36px]">
            <MiniSparkLine data={(trendData || []).map(d => d.value)} color={accent} height={36} />
            <div className="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none">
              <span className="bg-slate-800/80 text-white text-[10px] px-2 py-1 rounded-md flex items-center gap-1">
                <ZoomIn size={11} /> 放大详情
              </span>
            </div>
          </div>
        )}
      </div>
    )
  }

  return (
    <>
      {/* 折叠态卡片：常驻 grid 占位（不挤压相邻卡片），展开时由下方 fixed 覆盖层浮起 */}
      <div
        ref={cardRef}
        className={staticCls}
        onClick={() => onToggle(statKey)}
        title="点击放大详情"
      >
        {renderInner('compact')}
      </div>

      {/* 展开态：Portal 到 document.body 用 fixed 定位（避免祖先 transform 创建的包含块让 fixed 偏离视口）。
          真正的 Size Morph：卡片从收起态尺寸变形到目标尺寸。空间足够时左上锚点锁定；
          右侧卡片空间不足时，位置随尺寸一起平移到可视区，避免详情内容越界。
          内容两阶段：先让容器长大，展开内容再用 opacity 延迟淡入，避免初期被塞进小盒子 */}
      {typeof document !== 'undefined' && document.body && createPortal(
          overlayMounted && rect ? (
            <motion.div
              data-stat-overlay="true"
              className="fixed z-40 bg-white rounded-xl border border-slate-200 p-4 cursor-default"
              style={{
                overflow: 'hidden',
              }}
              initial={{
                top: openY,
                left: openX,
                width: rect.width,
                height: rect.height,
                boxShadow: '0px 2px 8px -2px rgba(15, 23, 42, 0)',
              }}
              animate={expanded ? {
                top: targetY,
                left: targetX,
                width: TARGET_W,
                height: TARGET_H,
                boxShadow: '0px 24px 48px -12px rgba(15, 23, 42, 0.22)',
              } : {
                top: openY,
                left: openX,
                width: rect.width,
                height: rect.height,
                boxShadow: '0px 2px 8px -2px rgba(15, 23, 42, 0)',
              }}
              transition={{
                top: { type: 'tween', duration: 0.48, ease: IOS_MORPH_EASE },
                left: { type: 'tween', duration: 0.48, ease: IOS_MORPH_EASE },
                width: { type: 'tween', duration: 0.48, ease: IOS_MORPH_EASE },
                height: { type: 'tween', duration: 0.48, ease: IOS_MORPH_EASE },
                boxShadow: { type: 'tween', duration: 0.48, ease: IOS_MORPH_EASE },
              }}
              onAnimationComplete={() => {
                if (!expandedRef.current) setOverlayMounted(false)
              }}
              onClick={(e) => {
                e.stopPropagation()
                // 收回途中点击浮层本身即可立即反向展开。
                if (!expandedRef.current) onToggle(statKey)
              }}
              onMouseDown={(e) => e.stopPropagation()}
            >
              {renderInner('expanded', expanded && detailOpen)}
            </motion.div>
          ) : null,
        document.body
      )}
    </>
  )
}
