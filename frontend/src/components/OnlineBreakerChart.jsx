// 同接熔断状态趋势图：展示熔断器状态随时间的变化（数据源 /api/status.online_breaker.trend）
// 阶梯折线 = 失败计数（0~3），虚线 = 熔断阈值；散点 = 状态事件（红=熔断打开/橙=重熔/绿=恢复）
import EChart from './EChart'

const STATE_META = {
  open: { color: '#ef4444', label: '熔断打开' },
  reopen: { color: '#f97316', label: '重熔' },
  closed: { color: '#22c55e', label: '恢复' },
}

function fmtTime(ts) {
  const d = new Date(ts * 1000)
  const p = (n) => String(n).padStart(2, '0')
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

export default function OnlineBreakerChart({ trend = [], threshold = 3 }) {
  if (!trend.length) return null
  const times = trend.map((p) => fmtTime(p.ts))
  const maxFails = Math.max(threshold, ...trend.map((p) => p.fails))

  const option = {
    title: {
      text: '同接熔断状态趋势',
      left: 8,
      top: 4,
      textStyle: { fontSize: 11, fontWeight: 600, color: '#475569' },
    },
    tooltip: {
      trigger: 'axis',
      formatter: (params) => {
        const i = params[0].dataIndex
        const p = trend[i]
        const meta = STATE_META[p.state]
        return `${fmtTime(p.ts)}<br/>失败计数: <b>${p.fails}</b><br/>事件: ${meta ? meta.label : p.state}`
      },
    },
    grid: { left: 34, right: 16, top: 30, bottom: 22 },
    xAxis: {
      type: 'category',
      data: times,
      boundaryGap: false,
      axisLabel: { fontSize: 9, color: '#94a3b8' },
      axisLine: { lineStyle: { color: '#e2e8f0' } },
    },
    yAxis: {
      type: 'value',
      min: 0,
      max: maxFails,
      interval: 1,
      axisLabel: { fontSize: 9, color: '#94a3b8' },
      splitLine: { lineStyle: { color: '#f1f5f9' } },
    },
    series: [
      {
        name: '失败计数',
        type: 'line',
        data: trend.map((p) => p.fails),
        step: 'end',
        symbol: 'none',
        lineStyle: { width: 1.5, color: '#94a3b8' },
        markLine: {
          silent: true,
          symbol: 'none',
          lineStyle: { type: 'dashed', color: '#ef4444' },
          label: { formatter: '阈值', position: 'insideEndTop', fontSize: 9, color: '#ef4444' },
          data: [{ yAxis: threshold }],
        },
      },
      {
        name: '状态事件',
        type: 'scatter',
        data: trend.map((p, i) => ({
          value: [i, p.fails],
          itemStyle: { color: STATE_META[p.state]?.color || '#94a3b8' },
        })),
        symbolSize: 9,
        emphasis: { scale: 1.6 },
      },
    ],
  }
  return <EChart option={option} height={110} className="online-breaker-chart" />
}
