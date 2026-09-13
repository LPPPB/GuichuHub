import { useState, useEffect } from 'react'
import { api } from '../utils/api'
import { Activity, Database, HardDrive, AlertTriangle, Loader2, RefreshCw, CheckCircle2 } from 'lucide-react'

// 数据体检：DB 健康概览（schema 版本、批次量、抓取残留等）
export default function DataHealth() {
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await api.getDevStats()
      if (res.success) setStats(res.data)
      else setError(res.message || '数据加载失败')
    } catch (e) {
      setError('数据加载失败')
    }
    setLoading(false)
  }

  useEffect(() => { load() }, [])

  const cards = stats ? [
    { icon: Database, label: 'Schema 版本', value: `V${stats.schema_version}`, color: 'text-sky-600' },
    { icon: Activity, label: '观测批次', value: stats.video_obs_batches, color: 'text-slate-800' },
    { icon: Activity, label: '观测行数', value: stats.video_obs_rows.toLocaleString(), color: 'text-slate-800' },
    { icon: HardDrive, label: '视频登记', value: stats.videos, color: 'text-slate-800' },
    { icon: HardDrive, label: 'UP 登记', value: stats.ups, color: 'text-slate-800' },
  ] : []

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-xs text-slate-500">
          SQLite 历史仓库健康概览：schema 迁移版本、观测数据量、抓取批次残留检测。
          <span className="text-slate-500 ml-1">残留 running = 进程被强杀未收尾的脏记录。</span>
        </p>
        <button
          onClick={load}
          disabled={loading}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-lg text-xs transition-colors disabled:opacity-50"
        >
          <RefreshCw size={12} className={loading ? 'animate-spin' : ''} /> 刷新
        </button>
      </div>

      {loading ? (
        <div className="flex items-center gap-2 text-sm text-slate-500 py-10">
          <Loader2 size={15} className="animate-spin" /> 加载中...
        </div>
      ) : error ? (
        <div className="flex items-center gap-2 text-sm text-red-600 py-10">
          <AlertTriangle size={15} /> {error}
        </div>
      ) : stats ? (
        <>
          {/* 概览卡 */}
          <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
            {cards.map((c, i) => (
              <div key={i} className="bg-white rounded-xl border border-slate-200 p-3">
                <div className="flex items-center gap-1.5 text-[11px] text-slate-500">
                  <c.icon size={13} />
                  {c.label}
                </div>
                <p className={`text-xl font-bold mt-1 ${c.color}`}>{c.value}</p>
              </div>
            ))}
          </div>

          {/* 抓取批次状态 */}
          <div className="bg-white rounded-xl border border-slate-200 p-4">
            <div className="flex items-center gap-2 mb-3">
              <p className="text-xs text-slate-700 font-semibold">抓取批次状态（crawl_runs）</p>
              {stats.crawl_runs?.running > 0 ? (
                <span className="text-[10px] px-2 py-0.5 rounded-full bg-amber-50 text-amber-700">
                  {stats.crawl_runs.running} 条 running 残留
                </span>
              ) : (
                <span className="text-[10px] px-2 py-0.5 rounded-full bg-green-50 text-green-700 flex items-center gap-1">
                  <CheckCircle2 size={10} /> 无残留
                </span>
              )}
            </div>
            <div className="flex flex-wrap gap-2">
              {Object.entries(stats.crawl_runs || {}).map(([k, v]) => (
                <span key={k} className={`text-xs px-2.5 py-1 rounded-lg border ${
                  k === 'running' ? 'bg-amber-50 border-amber-200 text-amber-700'
                  : k === 'success' ? 'bg-green-50 border-green-200 text-green-700'
                  : 'bg-red-50 border-red-200 text-red-600'
                }`}>
                  {k}: {v}
                </span>
              ))}
            </div>

            {stats.stale_running?.length > 0 && (
              <div className="mt-3">
                <p className="text-[11px] text-slate-500 mb-1.5">残留明细（进程被强杀未收尾）：</p>
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-slate-500 border-b border-slate-200">
                      <th className="py-1.5 text-left">ID</th>
                      <th className="py-1.5 text-left">开始时间</th>
                      <th className="py-1.5 text-left">触发源</th>
                    </tr>
                  </thead>
                  <tbody>
                    {stats.stale_running.map((r) => (
                      <tr key={r.id} className="border-b border-slate-100 text-slate-600">
                        <td className="py-1.5">{r.id}</td>
                        <td className="py-1.5">{r.started_at}</td>
                        <td className="py-1.5">{r.trigger}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      ) : null}
    </div>
  )
}
