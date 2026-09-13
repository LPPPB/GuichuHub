import { useEffect, useState } from 'react'
import { ExternalLink, MoreHorizontal, UserMinus } from 'lucide-react'
import { api } from '../utils/api'
import { proxyImage } from '../utils/image'

export default function ObservationRoster({ onRequestStop }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [menuMid, setMenuMid] = useState(null)
  const load = async () => {
    setError('')
    try {
      const res = await api.getObservationRoster()
      if (!res.success) throw new Error(res.message || '名单加载失败')
      setData(res.data)
    } catch (e) { setError(e.message || '名单加载失败') }
  }
  useEffect(() => { load() }, [])
  useEffect(() => {
    if (menuMid == null) return undefined
    const closeMenu = (event) => {
      if (!event.target.closest('[data-roster-menu]')) setMenuMid(null)
    }
    const closeOnEscape = (event) => {
      if (event.key === 'Escape') setMenuMid(null)
    }
    document.addEventListener('pointerdown', closeMenu)
    document.addEventListener('keydown', closeOnEscape)
    return () => {
      document.removeEventListener('pointerdown', closeMenu)
      document.removeEventListener('keydown', closeOnEscape)
    }
  }, [menuMid])
  const rows = (data?.ups || []).filter(up => `${up.name} ${up.mid}`.toLowerCase().includes(query.trim().toLowerCase()))
  return <section className="space-y-3">
    <div className="flex items-center justify-between gap-3">
      <h3 className="font-semibold text-slate-800">当前观测名单{data ? ` · ${data.total} 位` : ''}</h3>
      <button onClick={load} className="text-sm text-primary-600">刷新名单</button>
    </div>
    <p className="text-xs text-slate-500">这是当前启用的名单。停止观测须经审核，历史数据会保留。</p>
    <input aria-label="搜索观测名单" value={query} onChange={e => setQuery(e.target.value)} placeholder="搜索昵称或 MID" className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm" />
    {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
    {!data && !error && <p className="text-sm text-slate-500">名单加载中…</p>}
    {data && !rows.length && <p className="py-8 text-center text-sm text-slate-500">{query ? '没有匹配的UP主' : '暂无正在观测的UP主'}</p>}
    <div className="space-y-2 pb-2">
      {rows.map((up, index) => <div key={up.mid} className="relative flex items-center gap-3 rounded-xl border border-slate-100 p-3 transition-colors hover:border-slate-200 hover:bg-slate-50/60">
        <img src={proxyImage(up.face)} alt="" className="h-9 w-9 rounded-full bg-slate-100" />
        <div className="flex-1 min-w-0"><p className="truncate text-sm font-medium text-slate-800">{up.name || `UP ${up.mid}`}</p><p className="text-xs text-slate-500">MID {up.mid}</p></div>
        <div data-roster-menu className="relative shrink-0">
          <button
            type="button"
            aria-label={`${up.name || `UP ${up.mid}`}的更多操作`}
            aria-haspopup="menu"
            aria-expanded={menuMid === up.mid}
            onClick={() => setMenuMid(current => current === up.mid ? null : up.mid)}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-slate-400 transition-colors hover:bg-white hover:text-slate-700 focus:outline-none focus:ring-2 focus:ring-primary-500/25"
          >
            <MoreHorizontal size={18} />
          </button>
          {menuMid === up.mid && <div
            role="menu"
            aria-label={`${up.name || `UP ${up.mid}`}的操作`}
            className={`absolute right-0 z-30 w-40 rounded-xl border border-slate-200 bg-white p-1.5 shadow-lg ${index >= rows.length - 2 ? 'bottom-10' : 'top-10'}`}
          >
            <a
              role="menuitem"
              href={`https://space.bilibili.com/${up.mid}`}
              target="_blank"
              rel="noreferrer"
              onClick={() => setMenuMid(null)}
              className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm text-slate-700 hover:bg-slate-50"
            >
              <ExternalLink size={14} className="text-slate-400" />查看主页
            </a>
            {onRequestStop && <button
              type="button"
              role="menuitem"
              onClick={() => { setMenuMid(null); onRequestStop(up) }}
              className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm text-amber-700 hover:bg-amber-50"
            >
              <UserMinus size={14} />申请停止观测
            </button>}
          </div>}
        </div>
      </div>)}
    </div>
  </section>
}
