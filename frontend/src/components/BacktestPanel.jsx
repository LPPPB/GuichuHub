import { useState, useEffect } from 'react'
import { api } from '../utils/api'
import EChart from './EChart'
import {
  LineChart, Loader2, Play, AlertTriangle,
  ChevronDown, ChevronUp, TrendingUp, TrendingDown, Minus, RefreshCw,
} from 'lucide-react'

// 回测面板（V1 记录分事后验证）：
// 选历史批次 T → 用当时的 potential_score 榜单 → 验证 [T, T+window] 内
// 播放增量/增速是否真的和当时分数正相关（Spearman / Top-N 命中率 / 分桶单调性）。
const WINDOWS = [12, 24, 48]
const TOPS = [10, 20, 50]
const SORTS = [
  { id: 'rank_at_T', label: '当时排名' },
  { id: 'views_delta', label: '播放增量' },
  { id: 'growth_rate', label: '增速' },
]

const fmt = (n) => {
  if (n == null) return '-'
  if (n >= 10000) return `${(n / 10000).toFixed(1)}万`
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`
  return String(Math.round(n))
}

export default function BacktestPanel() {
  const [batches, setBatches] = useState([])
  const [ts, setTs] = useState('')
  const [windowH, setWindowH] = useState(48)
  const [topN, setTopN] = useState(20)
  const [sortBy, setSortBy] = useState('rank_at_T')
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(true)   // 批次加载中
  const [running, setRunning] = useState(false)  // 回测计算中
  const [msg, setMsg] = useState(null)
  const [expanded, setExpanded] = useState(null) // 展开复盘的行（bvid）
  const [review, setReview] = useState(null)     // {bvid, points, loading}

  useEffect(() => { loadBatches() }, [])

  const loadBatches = async () => {
    setLoading(true)
    setMsg(null)
    try {
      const res = await api.getDevBacktestBatches()
      if (res.success) {
        setBatches(res.data || [])
        if (res.data?.length) setTs(String(res.data[0].ts)) // 默认最近批次
        else setMsg({ type: 'info', text: '暂无带潜力分的历史批次（等待下次定时抓取）' })
      } else {
        setMsg({ type: 'error', text: res.message || '批次加载失败' })
      }
    } catch (e) {
      setMsg({ type: 'error', text: '批次加载失败' })
    }
    setLoading(false)
  }

  const run = async () => {
    if (!ts) return
    setRunning(true)
    setMsg(null)
    setResult(null)
    setExpanded(null)
    setReview(null)
    try {
      const res = await api.runDevBacktest(Number(ts), windowH, topN)
      if (res.success) setResult(res.data)
      else setMsg({ type: 'error', text: res.message || '回测失败' })
    } catch (e) {
      setMsg({ type: 'error', text: '回测失败（后端未启动或接口异常）' })
    }
    setRunning(false)
  }

  const toggleReview = async (bvid) => {
    if (expanded === bvid) {
      setExpanded(null)
      setReview(null)
      return
    }
    setExpanded(bvid)
    setReview({ bvid, points: null, loading: true })
    // 与后端 /api/videos/<bvid>/obs-trend 的 hours 上限(168)保持一致，
    // 超限会被后端静默截断，前端不传超限值避免"请求 300h 实返 168h"的误读
    const hours = Math.min(168, Math.ceil(Date.now() / 1000 / 3600 - Number(ts) / 3600) + windowH + 2)
    try {
      const res = await api.getVideoObsTrend(bvid, hours)
      setReview({
        bvid,
        points: res.success ? (res.data?.points || []) : [],
        loading: false,
      })
    } catch (e) {
      setReview({ bvid, points: [], loading: false })
    }
  }

  const m = result?.metrics
  const sorted = result
    ? [...result.table].sort((a, b) => {
        if (sortBy === 'rank_at_T') return a.rank_at_T - b.rank_at_T
        if (sortBy === 'views_delta') return b.views_delta - a.views_delta
        return b.growth_rate - a.growth_rate
      })
    : []

  // ── 图表 option ──
  const scatterOption = result && {
    grid: { left: 70, right: 24, top: 24, bottom: 44 },
    tooltip: {
      trigger: 'item',
      formatter: (p) => `分 ${p.value[0]} · 增速 ${(p.value[1] * 100).toFixed(1)}%`,
    },
    xAxis: { type: 'value', name: '当时潜力分', max: 100, axisLabel: { color: '#64748b' } },
    yAxis: { type: 'value', name: `${windowH}h增速`, axisLabel: { color: '#64748b', formatter: (v) => `${(v * 100).toFixed(0)}%` } },
    series: [{
      type: 'scatter',
      data: result.scatter.map((p) => [p.score, p.growth_rate]),
      symbolSize: 8,
      itemStyle: { color: 'rgba(249,115,22,0.75)' },
    }],
  }

  const bucketOption = result && {
    grid: { left: 70, right: 24, top: 24, bottom: 44 },
    tooltip: {
      trigger: 'axis',
      formatter: (ps) => {
        const b = result.buckets[ps[0].dataIndex]
        return `${b.name}<br/>n=${b.n} · 平均增量 ${fmt(b.avg_delta)} · 平均增速 ${(b.avg_growth * 100).toFixed(1)}%`
      },
    },
    xAxis: { type: 'category', data: result.buckets.map((b) => b.name), axisLabel: { color: '#64748b', fontSize: 10 } },
    yAxis: { type: 'value', name: '平均增速', axisLabel: { color: '#64748b', formatter: (v) => `${(v * 100).toFixed(0)}%` } },
    series: [{
      type: 'bar',
      data: result.buckets.map((b) => b.avg_growth),
      barGap: '-100%',
      itemStyle: { color: '#38bdf8' },
    }],
  }

  const reviewOption = review?.points?.length && {
    grid: { left: 64, right: 64, top: 36, bottom: 30 },
    legend: { data: ['潜力分', '播放量'], textStyle: { color: '#475569', fontSize: 11 }, top: 0 },
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: review.points.map((p) => {
      const d = new Date(p.ts * 1000)
      return `${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:00`
    }), axisLabel: { color: '#64748b', fontSize: 10 } },
    yAxis: [
      { type: 'value', name: '潜力分', max: 100, axisLabel: { color: '#64748b' } },
      { type: 'value', name: '播放量', axisLabel: { color: '#64748b', formatter: (v) => fmt(v) } },
    ],
    series: [
      { name: '潜力分', type: 'line', data: review.points.map((p) => p.potential_score), smooth: true, yAxisIndex: 0, lineStyle: { color: '#a855f7' }, itemStyle: { color: '#a855f7' } },
      { name: '播放量', type: 'line', data: review.points.map((p) => p.views), smooth: true, yAxisIndex: 1, lineStyle: { color: '#38bdf8' }, itemStyle: { color: '#38bdf8' } },
    ],
  }

  return (
    <div className="space-y-4">
      {/* 说明 + 参数区 */}
      <div className="bg-white rounded-xl border border-slate-200 p-4">
        <div className="flex items-start gap-2 text-xs text-slate-500 mb-3">
          <LineChart size={14} className="mt-0.5 text-primary-500 shrink-0" />
          <p>
            回测核心问题：<span className="text-slate-700">当时排在潜力榜前面的视频，之后是否真的更火？</span>
            选一个历史批次 T，用当时的潜力分榜单对比其后 {windowH}h 的实际播放表现。
            Spearman&gt;0.3、命中率&gt;50% 说明公式有预测力。
          </p>
        </div>

        <div className="flex flex-wrap items-end gap-3">
          {/* 批次选择 */}
          <label className="flex flex-col gap-1">
            <span className="text-[11px] text-slate-500">历史批次 T（当时评分榜单）</span>
            <select
              value={ts}
              onChange={(e) => setTs(e.target.value)}
              disabled={loading || running}
              className="bg-slate-50 border border-slate-300 rounded px-2 py-1.5 text-xs text-slate-800 focus:outline-none disabled:opacity-50 min-w-[150px]"
            >
              {loading && <option value="">加载中...</option>}
              {!loading && batches.length === 0 && <option value="">（无可用批次）</option>}
              {batches.map((b) => (
                <option key={b.ts} value={b.ts}>
                  {b.time}（{b.count} 个视频）
                </option>
              ))}
            </select>
          </label>

          {/* 窗口 */}
          <label className="flex flex-col gap-1">
            <span className="text-[11px] text-slate-500">预测窗口</span>
            <div className="flex gap-1">
              {WINDOWS.map((w) => (
                <button
                  key={w}
                  onClick={() => setWindowH(w)}
                  className={`px-2.5 py-1.5 rounded text-xs font-medium transition-colors ${
                    windowH === w ? 'bg-primary-500 text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                  }`}
                >
                  {w}h
                </button>
              ))}
            </div>
          </label>

          {/* Top N */}
          <label className="flex flex-col gap-1">
            <span className="text-[11px] text-slate-500">Top N</span>
            <div className="flex gap-1">
              {TOPS.map((n) => (
                <button
                  key={n}
                  onClick={() => setTopN(n)}
                  className={`px-2.5 py-1.5 rounded text-xs font-medium transition-colors ${
                    topN === n ? 'bg-primary-500 text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                  }`}
                >
                  {n}
                </button>
              ))}
            </div>
          </label>

          <button
            onClick={run}
            disabled={running || !ts}
            className="flex items-center gap-1.5 px-4 py-2 bg-green-600 hover:bg-green-500 text-white rounded-lg text-sm font-medium transition-colors disabled:opacity-50"
          >
            {running ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
            {running ? '计算中...' : '运行回测'}
          </button>

          <button
            onClick={loadBatches}
            disabled={loading}
            className="flex items-center gap-1.5 px-3 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-lg text-sm transition-colors disabled:opacity-50"
            title="刷新批次列表"
          >
            <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
            刷新批次
          </button>

          {msg && (
            <span className={`text-xs px-2 py-1.5 rounded flex items-center gap-1 ${
              msg.type === 'error' ? 'bg-red-50 text-red-600' : 'bg-slate-100 text-slate-600'
            }`}>
              {msg.type === 'error' && <AlertTriangle size={12} />}
              {msg.text}
            </span>
          )}
        </div>
      </div>

      {/* 回测结果 */}
      {result && m && (
        <>
          {/* 指标卡 */}
          <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
            {[
              {
                label: 'Spearman（分 vs 增速）',
                value: m.spearman.toFixed(2),
                tip: '排序一致性，>0.3 有预测力',
                color: m.spearman >= 0.3 ? 'text-green-600' : m.spearman > 0 ? 'text-amber-500' : 'text-red-600',
              },
              {
                label: `Top${result.meta.top_n} 命中率（增量）`,
                value: `${(m.hit_rate_delta * 100).toFixed(0)}%`,
                tip: '后来增量 Top N 中来自当时 Top N 的比例',
                color: m.hit_rate_delta >= 0.5 ? 'text-green-600' : m.hit_rate_delta > 0 ? 'text-amber-500' : 'text-red-600',
              },
              {
                label: `Top${result.meta.top_n} 命中率（增速）`,
                value: `${(m.hit_rate_growth * 100).toFixed(0)}%`,
                tip: '后来增速 Top N 中来自当时 Top N 的比例',
                color: m.hit_rate_growth >= 0.5 ? 'text-green-600' : m.hit_rate_growth > 0 ? 'text-amber-500' : 'text-red-600',
              },
              {
                label: '当时 Top N 后续排名',
                value: `↑${m.rank_up} ↓${m.rank_down} =${m.rank_same}`,
                tip: '当时 Top N 在后来增量榜单中的升降分布',
                color: 'text-slate-800',
              },
              {
                label: '验证样本',
                value: `${result.meta.n_verified}/${result.meta.n_scored}`,
                tip: `可验证数/当时有分数（${result.meta.n_unverified} 个窗口内无后续观测）`,
                color: 'text-slate-800',
              },
            ].map((c, i) => (
              <div key={i} className="bg-white rounded-xl border border-slate-200 p-3" title={c.tip}>
                <p className="text-[11px] text-slate-500">{c.label}</p>
                <p className={`text-xl font-bold mt-1 ${c.color}`}>{c.value}</p>
                <p className="text-[10px] text-slate-500 mt-1">{c.tip}</p>
              </div>
            ))}
          </div>

          {/* 图表 */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            <div className="bg-white rounded-xl border border-slate-200 p-3">
              <p className="text-xs text-slate-600 font-semibold mb-2">
                散点：当时潜力分 × 后{windowH}h增速
                <span className="text-slate-500 font-normal ml-2">右上倾斜 = 高分视频增速更快</span>
              </p>
              <EChart option={scatterOption} height={220} />
            </div>
            <div className="bg-white rounded-xl border border-slate-200 p-3">
              <p className="text-xs text-slate-600 font-semibold mb-2">
                分桶：按当时分等频分 5 组
                <span className="text-slate-500 font-normal ml-2">平均增速从左到右递增 = 排序有真实含义</span>
              </p>
              <EChart option={bucketOption} height={220} />
            </div>
          </div>

          {/* 对照表 */}
          <div className="bg-white rounded-xl border border-slate-200">
            <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200">
              <p className="text-xs text-slate-600 font-semibold">
                对照表：当时榜单 vs 后{windowH}h实际表现
                <span className="text-slate-500 font-normal ml-2">点击行展开单视频复盘（分数曲线 × 播放曲线）</span>
              </p>
              <div className="flex items-center gap-1.5">
                <span className="text-[11px] text-slate-500">排序</span>
                <select
                  value={sortBy}
                  onChange={(e) => setSortBy(e.target.value)}
                  className="bg-slate-50 border border-slate-300 rounded px-2 py-1 text-[11px] text-slate-700 focus:outline-none"
                >
                  {SORTS.map((s) => (
                    <option key={s.id} value={s.id}>{s.label}</option>
                  ))}
                </select>
              </div>
            </div>

            <div className="max-h-[420px] overflow-y-auto">
              <table className="w-full text-xs">
                <thead className="sticky top-0 bg-slate-50">
                  <tr className="text-slate-500 border-b border-slate-200">
                    <th className="px-3 py-2 text-left w-8">#</th>
                    <th className="px-3 py-2 text-left">视频</th>
                    <th className="px-3 py-2 text-right">当时分</th>
                    <th className="px-3 py-2 text-right">当时排名</th>
                    <th className="px-3 py-2 text-right">后来排名</th>
                    <th className="px-3 py-2 text-center">变化</th>
                    <th className="px-3 py-2 text-right">播放增量</th>
                    <th className="px-3 py-2 text-right">增速</th>
                    <th className="px-3 py-2 w-6" />
                  </tr>
                </thead>
                <tbody>
                  {sorted.map((row) => {
                    const change = row.rank_at_T - row.later_rank
                    const isOpen = expanded === row.bvid
                    return (
                      <TableRow
                        key={row.bvid}
                        row={row}
                        isOpen={isOpen}
                        onToggle={() => toggleReview(row.bvid)}
                        change={change}
                      />
                    )
                  })}
                  {sorted.length === 0 && (
                    <tr>
                      <td colSpan={9} className="px-3 py-6 text-center text-slate-500">
                        无有效样本（窗口内没有后续观测）
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>

            {/* 展开的复盘图 */}
            {expanded && review && (
              <div className="border-t border-slate-200 px-4 py-3">
                <p className="text-xs text-slate-500 mb-2">
                  单视频复盘：<span className="text-slate-700">{expanded}</span>
                  <span className="ml-2 text-slate-500">潜力分（紫）与播放量（蓝）的历史曲线</span>
                </p>
                {review.loading ? (
                  <div className="flex items-center gap-2 text-xs text-slate-500 py-6">
                    <Loader2 size={14} className="animate-spin" /> 加载观测时序...
                  </div>
                ) : review.points?.length ? (
                  <EChart option={reviewOption} height={200} />
                ) : (
                  <p className="text-xs text-slate-500 py-4 text-center">该视频无观测时序数据</p>
                )}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}

function TableRow({ row, isOpen, onToggle, change }) {
  return (
    <>
      <tr
        onClick={onToggle}
        className="border-b border-slate-100 hover:bg-slate-50 cursor-pointer"
      >
        <td className="px-3 py-2 text-slate-500">{row.rank_at_T}</td>
        <td className="px-3 py-2">
          <p className="text-slate-700 line-clamp-1 max-w-[260px]">{row.title || row.bvid}</p>
          <p className="text-[10px] text-slate-500">{row.author}</p>
        </td>
        <td className="px-3 py-2 text-right text-orange-500 font-medium">{row.score?.toFixed(1)}</td>
        <td className="px-3 py-2 text-right text-slate-600">#{row.rank_at_T}</td>
        <td className="px-3 py-2 text-right text-slate-600">#{row.later_rank}</td>
        <td className="px-3 py-2 text-center">
          {change > 0 ? (
            <span className="inline-flex items-center gap-0.5 text-green-600"><TrendingUp size={12} />{change}</span>
          ) : change < 0 ? (
            <span className="inline-flex items-center gap-0.5 text-red-600"><TrendingDown size={12} />{Math.abs(change)}</span>
          ) : (
            <span className="inline-flex items-center text-slate-500"><Minus size={12} /></span>
          )}
        </td>
        <td className="px-3 py-2 text-right text-slate-700">+{fmt(row.views_delta)}</td>
        <td className="px-3 py-2 text-right text-slate-700">{(row.growth_rate * 100).toFixed(1)}%</td>
        <td className="px-3 py-2 text-center text-slate-500">
          {isOpen ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
        </td>
      </tr>
    </>
  )
}
