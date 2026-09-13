import { useState, useEffect, useRef, useMemo } from 'react'
import { Flame, TrendingUp, AlertTriangle, ChevronDown, ChevronUp, Zap } from 'lucide-react'
import { api } from '../utils/api'
import { proxyImage } from '../utils/image'

function formatSpeed(v) {
  if (v >= 10000) return (v / 10000).toFixed(1) + '万'
  return Math.round(v).toLocaleString()
}

function formatViews(v) {
  if (v >= 100000000) return (v / 100000000).toFixed(1) + '亿'
  if (v >= 10000) return (v / 10000).toFixed(1) + '万'
  return Math.round(v).toLocaleString()
}

/**
 * iOS 股市风格 Sparkline（面积图 + 叠加折线 + 虚线昨日参照线）
 *   - 面积填充：线性渐变（顶部实心 20% → 底部全透明 0%）
 *   - 折线：加粗 1.6px，圆角线帽
 *   - baseline 虚线：Y 轴对齐 data[0] = 前收盘价参照（苹果股市灵魂）
 *   - props: { data, width=120, height=36, lineColor, gradientId }
 *     lineColor: 任意 CSS 颜色字符串，比如 'rgb(var(--neon-rose))'
 */
function Sparkline({ data, width = 120, height = 36, lineColor = 'rgb(var(--neon-rose))' }) {
  if (!data || data.length < 2) return null
  const min = Math.min(...data)
  const max = Math.max(...data)
  const range = max - min || 1
  const stepX = width / (data.length - 1)
  const padTop = 3, padBot = 2
  const plotH = height - padTop - padBot
  const pts = data.map((v, i) => ({
    x: i * stepX,
    y: padTop + plotH - ((v - min) / range) * plotH,
  }))
  const lineD = pts.map((p) => `L${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ').slice(1) // 去掉开头L
  const areaD = `M0,${height} L${pts.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' L')} L${width},${height} Z`
  // baseline = data[0] 昨日收盘价虚线
  const baseY = padTop + plotH - ((data[0] - min) / range) * plotH
  const gid = useMemo(() => 'kb-spark-' + Math.random().toString(36).slice(2, 9), [])
  return (
    <svg width={width} height={height} className="overflow-visible block">
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%"   stopColor={lineColor} stopOpacity="0.28" />
          <stop offset="100%" stopColor={lineColor} stopOpacity="0" />
        </linearGradient>
      </defs>
      {/* 昨日收盘价虚线（参照线，iOS Stocks 灵魂） */}
      <line
        x1="0" x2={width} y1={baseY.toFixed(1)} y2={baseY.toFixed(1)}
        stroke={lineColor}
        strokeDasharray="3,3"
        strokeWidth="0.8"
        strokeLinecap="round"
        opacity="0.55"
      />
      {/* 面积填充：渐变 */}
      <path d={areaD} fill={`url(#${gid})`} />
      {/* 叠加折线：加粗描边 */}
      <path
        d={`M${lineD}`}
        fill="none"
        stroke={lineColor}
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

// 增速档次：决定 PILL 颜色 & Sparkline 颜色（iOS 股市「红涨绿跌」二象 + 中国股市语义）
//   3 档：① 爆发 / TOP 高速 = rose 深红  ② 中速正增长 = pink 粉红  ③ 末位疲软 = emerald 绿（≈跌/涨不动）
//   绝对禁止 amber：琥珀橙既非上涨也非下跌，视觉语义暧昧，与 iOS 股市「只有红/绿二色」相悖。
function pickTiers(v, i) {
  if (v.is_bursting) {
    return { pill: 'kb-burst-pill kb-burst-pill--rose', line: 'rgb(var(--neon-rose))' }
  }
  // TOP 6（含爆发可能溢出）统一粉红上涨；末位（>=6）翡翠绿 = 疲软/近跌
  if (i < 6) return { pill: 'kb-burst-pill kb-burst-pill--pink',    line: 'rgb(var(--neon-pink))' }
  return         { pill: 'kb-burst-pill kb-burst-pill--emerald', line: 'rgb(var(--neon-emerald))' }
}

export default function BurstingVideos() {
  const [videos, setVideos] = useState(null)
  const [loading, setLoading] = useState(true)
  const [expanded, setExpanded] = useState(false)
  const listRef = useRef(null)
  const [renderCount, setRenderCount] = useState(8)
  const collapseTimer = useRef(null)
  const [maxH, setMaxH] = useState(null)

  const EXPAND_LIMIT = 15

  useEffect(() => {
    const el = listRef.current
    if (!el || !videos) return
    const compute = () => {
      const items = el.children
      let h = 0
      for (let i = 0; i < Math.min(8, items.length); i++) h += items[i].offsetHeight
      setMaxH(expanded ? el.scrollHeight : h)
    }
    compute()
    window.addEventListener('resize', compute)
    return () => window.removeEventListener('resize', compute)
  }, [videos, expanded, renderCount])

  const handleToggle = () => {
    clearTimeout(collapseTimer.current)
    if (expanded) {
      setExpanded(false)
      collapseTimer.current = setTimeout(() => setRenderCount(8), 500)
    } else {
      setRenderCount(Math.min(EXPAND_LIMIT, videos?.length || 8))
      setExpanded(true)
    }
  }

  useEffect(() => () => clearTimeout(collapseTimer.current), [])

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      try {
        const res = await api.getBurstingVideos()
        if (!cancelled && res.success && res.data) {
          setVideos(res.data.videos || [])
        }
      } catch (e) { /* 静默 */ } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    const timer = setInterval(load, 5 * 60 * 1000)
    return () => { cancelled = true; clearInterval(timer) }
  }, [])

  if (loading) {
    return (
      <section className="kb-card p-5">
        <div className="inner">
          <div className="flex items-center gap-2 mb-4">
            <Flame className="text-neon-rose" size={22} />
            <h2 className="text-lg font-bold text-haze-50">正在爆发</h2>
          </div>
          <div className="text-sm text-haze-400 py-4 text-center">加载增速数据...</div>
        </div>
      </section>
    )
  }

  if (!videos || videos.length === 0) return null

  const burstingCount = videos.filter(v => v.is_bursting).length

  return (
    <section className="kb-card p-5">
      <div className="inner">
        {/* 标题栏 */}
        <div className="flex items-center gap-2 mb-2">
          <Flame className="text-neon-rose shrink-0" size={22} />
          <h2 className="text-[18px] font-bold text-haze-50 tracking-tight">正在爆发</h2>
          {burstingCount > 0 ? (
            <span className="ml-auto kb-chip kb-chip--rose flex items-center gap-1">
              <AlertTriangle size={12} /> {burstingCount} 个爆发
            </span>
          ) : (
            <span className="ml-auto text-xs text-haze-400">近2小时增速 TOP</span>
          )}
        </div>

        <div className="relative">
          <div
            className="overflow-hidden transition-[max-height] duration-500 ease-in-out"
            style={{ maxHeight: maxH ? `${maxH}px` : undefined }}
          >
            {/* iOS 股市式：细分隔线 divide-y，不用 space-y */}
            <div
              ref={listRef}
              className="divide-y divide-[rgba(var(--void-700),1)]"
            >
              {videos.slice(0, renderCount).map((v, i) => {
                const tiers = pickTiers(v, i)
                return (
                  <a
                    key={v.bvid}
                    href={`https://www.bilibili.com/video/${v.bvid}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="kb-burst-row group hover:bg-[rgba(var(--void-800),0.35)] transition-colors -mx-1 px-1 rounded-md"
                  >
                    {/* [A] 排名色块（2.5rem 固定列宽） */}
                    <div
                      data-col="rank"
                      className={`w-10 h-8 rounded-lg inline-flex items-center justify-center text-[13px] font-bold shrink-0 ${
                        i < 3
                          ? 'bg-gradient-to-br from-neon-rose via-neon-pink to-neon-amber text-[rgb(var(--void-900))] shadow-[0_0_10px_-2px_rgba(var(--neon-rose),0.35)]'
                          : 'bg-[rgba(var(--void-700),1)] text-haze-300'
                      }`}
                    >{i + 1}</div>

                    {/* [B] 元信息（视频封面缩略图 + 标题/UP主 + ⚡爆发星标） */}
                    <div data-col="meta" className="min-w-0 flex flex-row items-center gap-2.5">
                      {/* 封面缩略图：56×40 比例（w-14 h-10），rounded-md 圆角，object-cover 防拉伸 */}
                      <div className="kb-burst-cover shrink-0 w-14 h-10 rounded-md overflow-hidden relative block bg-[rgba(var(--void-700),1)]">
                        <img
                          src={proxyImage(v.pic)}
                          alt=""
                          loading="lazy"
                          className="w-full h-full object-cover block"
                          draggable={false}
                        />
                      </div>
                      {/* 文字列：Zap⚡ + 标题（大粗字） + UP 主小字 */}
                      <div className="min-w-0 flex flex-col justify-center flex-1">
                        <div className="flex items-center gap-1 min-w-0">
                          {v.is_bursting && <Zap size={14} className="text-neon-rose shrink-0 -mt-[1px]" />}
                          <span className="text-[15px] font-bold text-haze-50 truncate leading-snug group-hover:text-primary-500 transition-colors">
                            {v.title}
                          </span>
                        </div>
                        <div className="text-[13px] text-haze-400 truncate leading-tight mt-0.5">
                          {v.owner?.name}
                        </div>
                      </div>
                    </div>

                    {/* [C] Sparkline 面积图（固定列 7.5rem = 120px） */}
                    <div data-col="spark" className="shrink-0 flex justify-end">
                      <Sparkline data={v.spark} width={120} height={36} lineColor={tiers.line} />
                    </div>

                    {/* [D] 数值柱：总量大粗字 + 增速 PILL 胶囊 */}
                    <div data-col="value" className="flex flex-col items-end justify-end gap-1 shrink-0 min-w-[92px]">
                      <div className="text-[17px] font-bold tabular-nums text-haze-50 leading-none">
                        {formatViews(v.views)}
                      </div>
                      <div className={tiers.pill}>
                        <TrendingUp size={12} />
                        {formatSpeed(v.speed)}/h
                      </div>
                    </div>
                  </a>
                )
              })}
            </div>
          </div>

          {/* 折叠遮罩：走 void-900 语义变量 避免写死 from-white */}
          {videos.length > 8 && (
            <div className={`pointer-events-none absolute inset-x-0 bottom-0 h-16 bg-gradient-to-t from-[rgb(var(--void-900))] via-[rgba(var(--void-900),0.6)] to-transparent transition-opacity duration-500 ${expanded ? 'opacity-0' : 'opacity-100'}`} />
          )}
        </div>

        {videos.length > 8 && (
          <div className="mt-1.5 flex justify-end">
            <button
              onClick={handleToggle}
              className={`flex items-center gap-0.5 text-xs font-medium transition-colors ${
                expanded ? 'text-haze-400 hover:text-haze-300' : 'text-primary-500 hover:underline'
              }`}
            >
              {expanded ? <><ChevronUp size={12} /> 收起</> : <>展开更多 <ChevronDown size={12} /></>}
            </button>
          </div>
        )}
      </div>
    </section>
  )
}
