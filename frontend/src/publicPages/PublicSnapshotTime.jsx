import { routeForTab } from '../routing/publicRoutes'

export default function PublicSnapshotTime({bootstrap, tab}) {
  if (!bootstrap) return null
  const tabs = tab === 'dashboard' ? Object.keys(bootstrap.confirmed_at) : [tab]
  return <div className="text-xs text-haze-400" aria-label="公开数据时间">
    {tabs.map(id => {
      const section = bootstrap.sections[id]
      const source = section?.source_updated_at
      const timestamp = source || bootstrap.confirmed_at[id]
      if (!Number.isFinite(timestamp) || timestamp <= 0) return null
      const iso = new Date(timestamp * 1000).toISOString()
      return <p key={id}>{routeForTab(id)?.title} · {source ? '数据更新时间' : '内容变更确认时间'}：<time dateTime={iso}>{iso.replace('T', ' ').replace('.000Z', ' UTC')}</time></p>
    })}
  </div>
}
