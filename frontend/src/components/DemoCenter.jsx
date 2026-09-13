import { useState } from 'react'
import ObsTrendChart from './ObsTrendChart'
import { PlayRankingChangeCard } from './TrendCharts'
import { FlaskConical, Gauge, Radar, GitCompare, Music2, BarChart3 } from 'lucide-react'

// 示例演示中心：各可视化样例的统一演示区。
// 样例通过 ObsTrendChart 的 points 注入通道渲染合成数据，不依赖后端 API。
// 未来新增图表（潜力分维度分解 / 公式版本对比 / BGM 热度曲线等）在此追加。

// ── 样例 1：同接精度标记点（合成数据，30 分钟一个观测点）──
const H = 1800
const now = Math.floor(Date.now() / 1000)
const mk = (i, online_count, online_precision) => ({
  ts: now - (13 - i) * H,
  views: 100000 + i * 1500,
  likes: 800, coins: 90, favorites: 60, shares: 30, comments: 260, danmaku: 380,
  online_count,
  online_precision,
})
const PRECISION_SAMPLE = [
  mk(0, 88, 'exact'),
  mk(1, 132, 'exact'),
  mk(2, 1000, 'k_plus'),
  mk(3, 2000, 'k_plus'),
  mk(4, 1750, 'exact'),
  mk(5, 11000, 'w'),
  mk(6, 15000, 'w'),
  mk(7, 12900, 'exact'),
  mk(8, 1000, 'k_plus'),
  mk(9, null, null),            // 断点：抓取失败
  mk(10, 2000, 'k_plus'),
  mk(11, 1980, 'exact'),
  mk(12, 26000, 'w'),
  mk(13, 30000, 'exact'),
]

// ── 样例 2：播放量排行变化 · 标签位置切换（合成极端数据）──
// 标签位置阈值 = maxAbs × 35%（本样例 maxAbs = 500万 → 阈值 = 175万）：
// |变化| > 175万 → 文字进柱内（白字）；|变化| < 175万 → 文字在柱外（与柱同色）
const RANK_BATCH_T = now - 12 * H
const RANKING_BATCHES = [
  {
    created_at: RANK_BATCH_T,
    analysis: {
      summary: { total_ups: 10 },
      play_ranking: [
        { mid: 'demo-h', name: 'UP-H', total_recent_views: 8000000 },
        { mid: 'demo-i', name: 'UP-I', total_recent_views: 5000000 },
        { mid: 'demo-e', name: 'UP-E', total_recent_views: 3000000 },
        { mid: 'demo-b', name: 'UP-B', total_recent_views: 2000000 },
        { mid: 'demo-d', name: 'UP-D', total_recent_views: 2000000 },
        { mid: 'demo-a', name: 'UP-A', total_recent_views: 1000000 },
        { mid: 'demo-c', name: 'UP-C', total_recent_views: 1000000 },
        { mid: 'demo-j', name: 'UP-J', total_recent_views: 1000000 },
        { mid: 'demo-f', name: 'UP-F', total_recent_views: 500000 },
        { mid: 'demo-g', name: 'UP-G', total_recent_views: 100000 },
      ],
    },
  },
  {
    created_at: now,
    analysis: {
      summary: { total_ups: 10 },
      play_ranking: [
        // 极长正柱（+500万，prevRank 6 → ↑5）
        { mid: 'demo-a', name: 'UP-A', total_recent_views: 6000000 },
        // 长正柱（+340万，prevRank 4 → ↑2）
        { mid: 'demo-b', name: 'UP-B', total_recent_views: 5400000 },
        // 临界正柱·柱内上沿（+200万，刚好 > 175万阈值，prevRank 5 → ↑2）
        { mid: 'demo-d', name: 'UP-D', total_recent_views: 4000000 },
        // 极长负柱（-450万，prevRank 1 → ↓3）
        { mid: 'demo-h', name: 'UP-H', total_recent_views: 3500000 },
        // 短正柱（+30万，prevRank 3 → ↓2）
        { mid: 'demo-e', name: 'UP-E', total_recent_views: 3300000 },
        // 长负柱（-200万，prevRank 2 → ↓4）
        { mid: 'demo-i', name: 'UP-I', total_recent_views: 3000000 },
        // 临界正柱·柱外下沿（+170万，刚好 < 175万阈值，prevRank 7 → →0）
        { mid: 'demo-c', name: 'UP-C', total_recent_views: 2700000 },
        // 极短正柱（+5万，prevRank 9 → ↑1）
        { mid: 'demo-f', name: 'UP-F', total_recent_views: 550000 },
        // 短负柱（-60万，prevRank 8 → ↓1）
        { mid: 'demo-j', name: 'UP-J', total_recent_views: 400000 },
        // 新上榜（上一批不存在 → 🆕 无柱）
        { mid: 'demo-k', name: 'UP-K', total_recent_views: 105000 },
      ],
    },
  },
]

// 预期对照表（按最新榜单顺序，供核对渲染结果）
const RANKING_EXPECT = [
  { name: 'UP-A', change: '+500万', expect: '柱内(白)·超长', tone: 'inside' },
  { name: 'UP-B', change: '+340万', expect: '柱内(白)', tone: 'inside' },
  { name: 'UP-D', change: '+200万', expect: '柱内(白)·临界上', tone: 'inside' },
  { name: 'UP-H', change: '-450万', expect: '柱内(白)·超长', tone: 'inside' },
  { name: 'UP-E', change: '+30万', expect: '柱外(绿)·短', tone: 'up' },
  { name: 'UP-I', change: '-200万', expect: '柱内(白)', tone: 'inside' },
  { name: 'UP-C', change: '+170万', expect: '柱外(绿)·临界下', tone: 'up' },
  { name: 'UP-F', change: '+5万', expect: '柱外(绿)·极短', tone: 'up' },
  { name: 'UP-J', change: '-60万', expect: '柱外(红)', tone: 'down' },
  { name: 'UP-K', change: '—', expect: '新上榜(🆕 无柱)', tone: 'new' },
]

// 未来样例占位（规划中）
const FUTURE = [
  { icon: Gauge, title: '潜力分维度分解', desc: 'heat/quality/trend/online 四维雷达或堆叠条' },
  { icon: GitCompare, title: '公式版本对比', desc: '同一批次不同公式重放的榜单差异（回测 V2 配套）' },
  { icon: Music2, title: 'BGM 热度曲线', desc: '热梗 BGM 的多日热度走势' },
  { icon: Radar, title: 'UP 画像雷达', desc: 'UP 的分区分布/互动质量/活跃度画像' },
]

export default function DemoCenter() {
  const [sample, setSample] = useState('precision') // 当前样例（未来扩展多个）

  return (
    <div className="space-y-4">
      <p className="text-xs text-slate-500">
        可视化样例演示区：合成数据直接注入图表组件（不走后端），用于验证/预览渲染效果。
        当前 2 个样例，未来在此追加。
      </p>

      {/* 样例选择（未来扩展） */}
      <div className="flex gap-1.5">
        <button
          onClick={() => setSample('precision')}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
            sample === 'precision' ? 'bg-primary-500 text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
          }`}
        >
          <FlaskConical size={13} />
          同接精度标记点
        </button>
        <button
          onClick={() => setSample('ranking')}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
            sample === 'ranking' ? 'bg-primary-500 text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
          }`}
        >
          <BarChart3 size={13} />
          排行柱标签位置
        </button>
      </div>

      {sample === 'precision' && (
        <div className="bg-white rounded-xl border border-slate-200 p-4">
          <div className="flex items-center gap-2 mb-1">
            <p className="text-sm font-semibold text-slate-800">同接精度标记点</p>
            <span className="text-[10px] px-2 py-0.5 rounded-full bg-slate-100 text-slate-500">样例 1/2</span>
          </div>
          <p className="text-xs text-slate-500 mb-4">
            点"同接"按钮查看：精确点=实心圆，近似点（"1000+"/"1.1万"）=空心圆 + tooltip"（约）"，NULL=断点不连线。
          </p>
          <div className="bg-slate-50 rounded-lg p-3">
            <ObsTrendChart bvid="demo-precision" points={PRECISION_SAMPLE} />
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 mt-4">
            <div className="flex items-start gap-2 bg-slate-50 rounded-lg p-3">
              <span className="w-3 h-3 rounded-full bg-orange-500 mt-0.5 inline-block shrink-0" />
              <p className="text-xs text-slate-600">实心圆 = 精确（exact），B站返回精确数字，tooltip 显示原值</p>
            </div>
            <div className="flex items-start gap-2 bg-slate-50 rounded-lg p-3">
              <span className="w-3 h-3 rounded-full border-2 border-orange-500 bg-transparent mt-0.5 inline-block shrink-0" />
              <p className="text-xs text-slate-600">空心圆 = 近似（k_plus/w），"1000+（约）"/"1.1万（约）"如实表达取整</p>
            </div>
            <div className="flex items-start gap-2 bg-slate-50 rounded-lg p-3">
              <span className="w-1.5 h-6 bg-slate-400 rounded mt-0.5 inline-block shrink-0" />
              <p className="text-xs text-slate-600">断点 = 抓取失败（NULL），不跨空连线</p>
            </div>
          </div>
        </div>
      )}

      {sample === 'ranking' && (
        <div className="space-y-4">
          <div className="bg-white rounded-xl border border-slate-200 p-4">
            <div className="flex items-center gap-2 mb-1">
              <p className="text-sm font-semibold text-slate-800">排行柱标签位置切换</p>
              <span className="text-[10px] px-2 py-0.5 rounded-full bg-slate-100 text-slate-500">样例 2/2</span>
            </div>
            <p className="text-xs text-slate-500">
              阈值 = 最大变化 × 35%（本样例 maxAbs = 500万 → 阈值 = <b>175万</b>）：|变化| &gt; 175万 → 文字进柱内（白字），
              |变化| &lt; 175万 → 文字在柱外（与柱同色）。构造了超长柱（±450万/±500万）、极短柱（+5万/+30万）、
              临界柱（+170万/+200万 贴阈值两侧）与新上榜（🆕 无柱）来验证切换效果。
            </p>
          </div>
          <PlayRankingChangeCard batches={RANKING_BATCHES} />
          <div className="bg-white rounded-xl border border-slate-200 p-4">
            <p className="text-xs font-semibold text-slate-600 mb-2">预期对照表（按最新榜单顺序，自上而下）</p>
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2">
              {RANKING_EXPECT.map((r, i) => (
                <div key={i} className="bg-slate-50 rounded-lg p-2 text-[11px] text-slate-600">
                  <span className="font-medium text-slate-800">{r.name}</span>
                  <span className="ml-1.5">{r.change}</span>
                  <div className={`mt-0.5 font-medium ${
                    r.tone === 'inside' ? 'text-slate-500' : r.tone === 'up' ? 'text-green-600' : r.tone === 'down' ? 'text-red-600' : 'text-amber-600'
                  }`}>
                    {r.expect}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* 未来样例占位 */}
      <div>
        <p className="text-[11px] text-slate-500 mb-2">规划中（回测 V2 / 后续迭代）</p>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          {FUTURE.map((f, i) => (
            <div key={i} className="bg-slate-50/60 rounded-xl border border-dashed border-slate-300 p-3 opacity-70">
              <f.icon size={15} className="text-slate-500" />
              <p className="text-xs text-slate-600 font-medium mt-2">{f.title}</p>
              <p className="text-[11px] text-slate-500 mt-1">{f.desc}</p>
              <span className="inline-block mt-2 text-[10px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500">规划中</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
