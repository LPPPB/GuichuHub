import { useState, lazy, Suspense } from 'react'
import { Layers, LineChart, Activity, FlaskConical, ShieldCheck } from 'lucide-react'

// 开发者后台：整页控制台，五个模块按需懒加载
// 模块全部挂载后用 hidden 切换（保留各自状态：回测结果/配置草稿不因切 tab 丢失）
const MemeConfig = lazy(() => import('./DevPanel'))
const BacktestPanel = lazy(() => import('./BacktestPanel'))
const DataHealth = lazy(() => import('./DataHealth'))
const DemoCenter = lazy(() => import('./DemoCenter'))
const AdminAccountsPanel = lazy(() => import('./AdminAccountsPanel'))
const ObservationAdmin = lazy(() => import('./ObservationAdmin'))

const MODULES = [
  { id: 'observation', label: 'UP主观测', icon: Activity, desc: '观测名单 · 添加与停止申请 · 审核' },
  { id: 'admins', label: '管理员管理', icon: ShieldCheck, desc: 'B站账号管理员名单与采集账号' },
  { id: 'meme', label: '词汇规则', icon: Layers, desc: '公共底座 + 榜单规则 + 规则测试' },
  { id: 'backtest', label: '回测面板', icon: LineChart, desc: '验证潜力分公式的预测力' },
  { id: 'health', label: '数据体检', icon: Activity, desc: 'DB 健康概览与脏数据' },
  { id: 'demo', label: '示例演示', icon: FlaskConical, desc: '可视化样例中心' },
]

export default function DevConsole() {
  const [module, setModule] = useState('admins')

  return (
    <div className="min-h-full bg-slate-50 text-slate-800">
      <div className="max-w-7xl mx-auto px-4 py-5">
        {/* 头部 */}
        <div className="mb-4">
          <h2 className="text-lg font-bold flex items-center gap-2">
            <span className="w-2 h-5 bg-primary-400 rounded-full inline-block" />
            开发者后台
          </h2>
          <p className="text-xs text-slate-500 mt-1">
            管理员账号与采集凭证 · 配置梗素材库 · 回测评分预测力 · 体检数据健康 · 演示可视化样例
          </p>
        </div>

        {/* 模块导航 */}
        <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-2.5 mb-5">
          {MODULES.map((m) => (
            <button
              key={m.id}
              onClick={() => setModule(m.id)}
              className={`text-left rounded-xl border p-3 transition-colors ${
                module === m.id
                  ? 'bg-white border-primary-300 shadow-sm'
                : 'bg-white border-slate-200 hover:border-slate-300'
              }`}
            >
              <div className="flex items-center gap-2">
                <m.icon size={16} className={module === m.id ? 'text-primary-500' : 'text-slate-500'} />
                <span className="text-sm font-semibold">{m.label}</span>
              </div>
              <p className="text-xs text-slate-500 mt-1">{m.desc}</p>
            </button>
          ))}
        </div>

        {/* 模块内容（全部挂载，hidden 切换） */}
        <Suspense fallback={<div className="text-sm text-slate-500 py-10 text-center">模块加载中...</div>}>
          {module === 'observation' && <ObservationAdmin />}
          <div className={module === 'admins' ? '' : 'hidden'}>
            <AdminAccountsPanel />
          </div>
          <div className={module === 'meme' ? '' : 'hidden'}>
            <MemeConfig />
          </div>
          <div className={module === 'backtest' ? '' : 'hidden'}>
            <BacktestPanel />
          </div>
          <div className={module === 'health' ? '' : 'hidden'}>
            <DataHealth />
          </div>
          <div className={module === 'demo' ? '' : 'hidden'}>
            <DemoCenter />
          </div>
        </Suspense>
      </div>
    </div>
  )
}
