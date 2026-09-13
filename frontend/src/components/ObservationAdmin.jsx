import { useState } from 'react'
import ObservationRoster from './ObservationRoster'
import UpRequestsAdmin from './UpRequestsAdmin'
import UpTrendsSetup from './UpTrendsSetup'

export default function ObservationAdmin() {
  const [tab, setTab] = useState('review')
  const [revision, setRevision] = useState(0)
  return <section className="space-y-4">
    <div><h2 className="text-lg font-bold">UP主观测管理</h2><p className="mt-1 text-sm text-slate-500">审核添加与停止申请，查看当前名单，维护观测配置。</p></div>
    <nav aria-label="观测管理" className="flex flex-wrap gap-2">
      {[['review', '申请审核'], ['roster', '当前名单'], ['config', '名单配置']].map(([id, title]) => <button key={id} onClick={() => setTab(id)} className={`rounded-lg px-4 py-2 text-sm ${tab === id ? 'bg-primary-500 text-white' : 'bg-white border border-slate-200 text-slate-600'}`}>{title}</button>)}
    </nav>
    {tab === 'review' && <UpRequestsAdmin embedded />}
    {tab === 'roster' && <div className="rounded-2xl bg-white border border-slate-200 p-5"><ObservationRoster key={revision} /></div>}
    {tab === 'config' && <><p className="text-sm text-slate-600 rounded-lg bg-primary-50 p-3">勾选表示启用观测，取消勾选表示停止观测，保存后生效。包含已停用记录，可重新勾选恢复。名单不随互粉关系自动增删。</p><UpTrendsSetup localOnly onComplete={() => { setRevision(n => n + 1); setTab('roster') }} onCancel={() => setTab('roster')} /></>}
  </section>
}
