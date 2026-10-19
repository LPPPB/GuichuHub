import { useState, useMemo, useEffect } from 'react'
import EChart from './EChart'
import { api } from '../utils/api'

// 指标配置：key → { label, 颜色, Y轴index(0左/1右), 是否连线补NULL, 是否虚线 }
const METRICS = {
  views: { label: '播放量', color: '#3b82f6', yAxis: 0, connectNulls: true },
  online_count: { label: '同接', color: '#f97316', yAxis: 1, connectNulls: false },  // NULL 断点
  interaction_rate: { label: '互动率', color: '#10b981', yAxis: 1, connectNulls: false, dashed: true },
}

function formatNum(v) {
  if (v == null) return '—'
  if (v >= 10000) return (v / 10000).toFixed(1) + '万'
  return Number(v).toLocaleString()
}

// 同接 tooltip 展示：按精度还原 B 站原始展示格式，近似值追加"（约）"如实反映取整
function formatOnline(value, precision) {
  if (precision === 'k_plus') return `${value}+（约）`
  if (precision === 'w') {
    const w = value / 10000
    return `${w % 1 === 0 ? w : w.toFixed(1)}万（约）`
  }
  return formatNum(value)  // exact / 未知精度（老数据）按精确兜底
}

// 支持两种数据来源：
//  - 常规：传入 bvid，挂载后从 /api/videos/<bvid>/obs-trend 拉取
//  - 演示/测试：传入 points（观测点数组），直接渲染、跳过 API 拉取
export default function ObsTrendChart({ bvid, observedAt, points: demoPoints }) {
  const [points, setPoints] = useState(demoPoints ?? null)  // null=未加载, []=空
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [active, setActive] = useState(['views'])  // 默认播放量，可叠加

  // 按需加载：VideoCard 展开时才渲染本组件，挂载即请求（注入演示数据时跳过）
  useEffect(() => {
    if (demoPoints) {
      setPoints(demoPoints)
      setError(null)
      setLoading(false)
      return
    }
    let cancelled = false
    setPoints(null)
    setError(null)
    setLoading(true)
    api.getVideoObsTrend(bvid, 48)
      .then(res => {
        if (cancelled) return
        if (res.success && res.data) setPoints(res.data.points || [])
        else setError(res.message || '加载失败')
      })
      .catch(e => { if (!cancelled) setError(e.message) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [bvid, observedAt, demoPoints])

  const toggle = (key) => {
    setActive(prev => prev.includes(key) ? prev.filter(k => k !== key) : [...prev, key])
  }

  const option = useMemo(() => {
    if (!points || points.length === 0) return null

    const buildData = (key) => points.map(p => {
      let val
      if (key === 'views') val = p.views
      else if (key === 'online_count') val = p.online_count
      else if (key === 'interaction_rate') {
        // 互动率 = (赞+币+藏+转) / 播放 × 100
        const counts = [p.views, p.likes, p.coins, p.favorites, p.shares]
        const complete = counts.every(v => v != null && v !== '' && typeof v !== 'boolean' && Number.isFinite(Number(v)) && Number(v) >= 0)
        const inter = complete ? counts.slice(1).reduce((sum, v) => sum + Number(v), 0) : null
        val = complete && Number(p.views) > 0 ? +(inter / Number(p.views) * 100).toFixed(2) : null
      }
      // 同接近似点（"1000+"/"1.1万"，B站按千/万取整）：空心圆标记，与精确点（实心）区分
      if (key === 'online_count' && val != null && p.online_precision && p.online_precision !== 'exact') {
        return {
          value: [p.ts * 1000, val],
          symbol: 'circle',
          symbolSize: 4,
          itemStyle: { color: 'transparent', borderColor: METRICS.online_count.color, borderWidth: 1.5 },
        }
      }
      return [p.ts * 1000, val]
    })

    const series = active.map(key => {
      const m = METRICS[key]
      return {
        name: m.label,
        type: 'line',
        data: buildData(key),
        yAxisIndex: m.yAxis,
        smooth: key !== 'online_count',  // 同接波动大，不平滑
        symbol: 'circle',
        symbolSize: key === 'online_count' ? 4 : 5,
        itemStyle: { color: m.color },
        // 显式指定线的颜色：近似点 itemStyle 为透明+描边，不显式指定会把折线也画成透明
        lineStyle: { width: 2, color: m.color, type: m.dashed ? 'dashed' : 'solid' },
        connectNulls: m.connectNulls,
      }
    })

    return {
      grid: { left: 48, right: 48, top: 16, bottom: 28 },
      tooltip: {
        trigger: 'axis',
        backgroundColor: 'rgba(255,255,255,0.96)',
        borderColor: '#e2e8f0',
        textStyle: { fontSize: 11, color: '#334155' },
        formatter: (params) => {
          const d = new Date(params[0].value[0])
          const time = `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
          let html = `<div style="font-size:11px;color:#64748b;margin-bottom:4px">${time}</div>`
          params.forEach(p => {
            const key = Object.keys(METRICS).find(k => METRICS[k].label === p.seriesName)
            let display
            if (p.value[1] == null) display = '—'
            else if (key === 'interaction_rate') display = p.value[1] + '%'
            // 同接按精度还原原始格式（"1000+（约）"/"1.1万（约）"），如实反映 B 站取整
            else if (key === 'online_count') display = formatOnline(p.value[1], points[p.dataIndex]?.online_precision)
            else display = formatNum(p.value[1])
            html += `<div style="display:flex;align-items:center;gap:8px;line-height:18px">
              <span style="display:inline-block;width:8px;height:8px;background:${METRICS[key]?.color || p.color};border-radius:50%"></span>
              <span>${p.seriesName}</span>
              <span style="margin-left:12px;font-weight:600">${display}</span>
            </div>`
          })
          return html
        },
      },
      xAxis: {
        type: 'time',
        axisLabel: { fontSize: 10, color: '#94a3b8' },
        axisLine: { lineStyle: { color: '#e2e8f0' } },
      },
      yAxis: [
        {
          type: 'value',
          axisLabel: { fontSize: 10, color: '#94a3b8', formatter: v => v >= 10000 ? (v / 10000).toFixed(1) + '万' : v },
          splitLine: { lineStyle: { color: '#f1f5f9' } },
        },
        {
          type: 'value',
          axisLabel: { fontSize: 10, color: '#94a3b8' },
          splitLine: { show: false },
        },
      ],
      series,
    }
  }, [points, active])

  if (loading) {
    return (
      <div className="flex items-center justify-center py-8 text-sm text-slate-400">
        <div className="w-4 h-4 border-2 border-primary-500 border-t-transparent rounded-full animate-spin mr-2" />
        加载观测数据...
      </div>
    )
  }

  if (error) {
    return <div className="py-6 text-center text-sm text-slate-400">{error}</div>
  }

  if (!points || points.length < 3) {
    return (
      <div className="py-6 text-center text-sm text-slate-400">
        数据积累中（当前 {points?.length || 0} 个观测点，需 ≥3 个绘制曲线）
      </div>
    )
  }

  return (
    <div className="mt-3">
      <div className="flex items-center gap-2 mb-1">
        <span className="text-xs text-slate-400">近 48 小时观测（{points.length} 个点）</span>
        {active.includes('online_count') && points.some(p => p.online_precision && p.online_precision !== 'exact') && (
          <span className="text-[10px] text-orange-400/80">空心圆=同接近似值（B站按千/万取整）</span>
        )}
        <div className="flex gap-1 ml-auto">
          {Object.entries(METRICS).map(([key, m]) => {
            const on = active.includes(key)
            return (
              <button
                key={key}
                onClick={() => toggle(key)}
                className={`text-xs px-2 py-1 rounded-md border transition-all ${
                  on ? 'text-white border-transparent' : 'bg-white text-slate-500 border-slate-200 hover:border-slate-300'
                }`}
                style={on ? { backgroundColor: m.color } : {}}
              >
                {m.label}
              </button>
            )
          })}
        </div>
      </div>
      <EChart option={option} height={200} />
    </div>
  )
}
