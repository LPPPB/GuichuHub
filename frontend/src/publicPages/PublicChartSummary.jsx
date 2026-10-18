export default function PublicChartSummary({items = []}) {
  if (!items.length) return <p className="text-xs text-slate-500 p-4">暂无可用统计</p>
  return <dl className="space-y-1 p-4 text-xs text-slate-600" aria-label="图表统计摘要">
    {items.slice(0, 20).map((item,index)=><div key={index} className="flex justify-between gap-3">
      <dt>{item.label}</dt><dd>{item.value ?? '—'}</dd>
    </div>)}
  </dl>
}
