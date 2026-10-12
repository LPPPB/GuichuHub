export function observationTime(timestamp, full = false) {
  if (timestamp == null || !Number.isFinite(Number(timestamp))) return '时间未知'
  const date = new Date(Number(timestamp) * 1000)
  if (Number.isNaN(date.getTime())) return '时间未知'
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai', ...(full ? { month: '2-digit', day: '2-digit' } : {}),
    hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(date)
}

export default function RadarDetails({ axis, radar }) {
  const components = axis.components || []
  const reference = axis.reference || components[0]?.reference
  const unit = axis.unit || '次/千播放'
  return <>
    <p className="font-semibold text-haze-100">{axis.label} · {axis.score == null ? '—' : `${axis.score}分`}</p>
    {axis.status !== 'available' && <p>{axis.reason || '暂无可信观测'}</p>}
    <dl>
      {components.map(component => <div key={component.id} className="flex flex-wrap justify-between gap-x-3">
        <dt>{component.label}</dt>
        <dd><span>{component.raw == null ? '—' : `${Number(component.raw).toLocaleString('zh-CN', { maximumFractionDigits: 2 })} ${unit}`}</span>
          <span className="block text-haze-400">{component.score == null ? component.reason || '子指标暂无分位分' : `分位 ${component.score}分`}</span>
        </dd>
      </div>)}
    </dl>
    {axis.window_hours != null && <p>观测窗口 {Number(axis.window_hours).toFixed(1)} 小时 · 新增 {Number(axis.growth_views).toLocaleString()} 播放</p>}
    {components.length > 1 && <p>综合相对分：两个子指标的分位分等权平均。</p>}
    {reference && <p>参考 {reference.count} 条{reference.age_min_days == null ? '观测样本' :
      ` · 发布 ${reference.age_min_days}～${reference.age_max_days ?? '更早'} 天`}</p>}
    <p>数据 {observationTime(radar.observed_at, true)}（北京时间）</p>
    <p className="break-all text-haze-400">基线 {radar.baseline_version || '暂缺'}</p>
  </>
}
