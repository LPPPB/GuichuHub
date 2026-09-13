import { describe, it, expect, vi, afterEach } from 'vitest'
import { render } from '@testing-library/react'

// 切断 EChart 的 echarts 依赖链（jsdom 无 canvas）与 api 副作用，
// 使测试只聚焦 computeRankingData 纯函数逻辑，不触发图表渲染。
vi.mock('./EChart', () => ({ default: () => null }))
vi.mock('../utils/api', () => ({ api: {} }))

import { buildFrequencySeries, computeRankingData, PlayRankingChangeCard } from './TrendCharts'

// ── 测试数据 helper ──
// up(mid, name, views, extra) 构造单个 UP；batch(ranking) 构造一个带 analysis.play_ranking 的批次
const up = (mid, name, views, extra = {}) => ({ mid, name, total_recent_views: views, ...extra })
const batch = (playRanking, extra = {}) => ({ analysis: { play_ranking: playRanking, ...extra } })

const calendarWeeks = (year) => {
  const cells = []
  const cursor = new Date(year, 0, 1)
  while (cursor.getFullYear() === year) {
    const date = new Date(cursor)
    const dateStr = `${year}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
    cells.push({ date, dateStr, isInRange: true, count: 1, views: 100 })
    cursor.setDate(cursor.getDate() + 1)
  }
  return Array.from({ length: Math.ceil(cells.length / 7) }, (_, i) => cells.slice(i * 7, i * 7 + 7))
}

describe('buildFrequencySeries — 发布趋势区间与粒度', () => {
  const weeks = calendarWeeks(2026)
  const now = new Date(2026, 8, 6)

  it('近30天按日展示，并截止今天而不是补未来零值', () => {
    const result = buildFrequencySeries(weeks, 2026, '30d', now)
    expect(result.granularity).toBe('day')
    expect(result.data).toHaveLength(30)
    expect(result.data[0].dateStr).toBe('2026-08-08')
    expect(result.data.at(-1).dateStr).toBe('2026-09-06')
  })

  it('近90天默认保留日粒度', () => {
    const result = buildFrequencySeries(weeks, 2026, '90d', now)
    expect(result.granularity).toBe('day')
    expect(result.data).toHaveLength(90)
    expect(result.data.at(-1).count).toBe(1)
  })

  it('近半年和全年自动按周聚合', () => {
    const halfYear = buildFrequencySeries(weeks, 2026, '180d', now)
    const fullYear = buildFrequencySeries(weeks, 2026, 'year', now)
    expect(halfYear.granularity).toBe('week')
    expect(halfYear.data.length).toBeGreaterThanOrEqual(25)
    expect(halfYear.data.length).toBeLessThanOrEqual(27)
    expect(halfYear.data.reduce((sum, point) => sum + point.count, 0)).toBe(180)
    expect(fullYear.granularity).toBe('week')
    expect(fullYear.data.reduce((sum, point) => sum + point.count, 0)).toBe(249)
  })
})

describe('computeRankingData — 播放量排行变化排序逻辑', () => {
  // ── 1. 核心排序：按 |播放量变化| 降序，涨跌双向对称；changeRank 连续；currentRank 保持播放量名次 ──
  it('按 |播放量变化| 降序排序，跌得多的也排前；changeRank 连续 1-N；currentRank 保持播放量名次（不连续）', () => {
    const latest = batch([
      up(1, 'UP大主', 1000),  // prev=900 → +100
      up(2, 'UP爆发', 300),   // prev=100  → +200
      up(3, 'UP下跌', 500),   // prev=800  → -300  ← 变化幅度最大
      up(4, 'UP稳定', 200),   // prev=200  → 0
    ])
    const previous = batch([
      up(3, 'UP下跌', 800),   // prev 排第1
      up(1, 'UP大主', 900),   // prev 排第2
      up(2, 'UP爆发', 100),   // prev 排第3
      up(4, 'UP稳定', 200),   // prev 排第4
    ])

    const result = computeRankingData(latest, previous)

    // 顺序：|−300| > |+200| > |+100| > |0|
    expect(result.map(r => r.name)).toEqual(['UP下跌', 'UP爆发', 'UP大主', 'UP稳定'])
    // changeRank 连续 1-4
    expect(result.map(r => r.changeRank)).toEqual([1, 2, 3, 4])
    // currentRank 保持各 UP 在最新批的播放量名次（3,2,1,4 — 不连续，与 changeRank 解耦）
    expect(result.map(r => r.currentRank)).toEqual([3, 2, 1, 4])
    // viewsChange 涨跌双向（负值也参与排序）
    expect(result.map(r => r.viewsChange)).toEqual([-300, 200, 100, 0])
    // maxAbsChange = 全体最大绝对值
    expect(result[0].maxAbsChange).toBe(300)
  })

  // ── 2. viewsChangePct 计算：prevViews=0 时为 null（防除零），但 viewsChange 仍可算 ──
  it('viewsChangePct = 变化值/上一批播放 × 100；prevViews=0 时为 null，但 viewsChange 仍算', () => {
    const latest = batch([
      up(1, 'A', 200),  // prev=100 → +100, +100%
      up(2, 'B', 50),   // prev=0   → +50,  pct=null（防除零）
    ])
    const previous = batch([up(1, 'A', 100), up(2, 'B', 0)])

    const result = computeRankingData(latest, previous)
    const a = result.find(r => r.name === 'A')
    const b = result.find(r => r.name === 'B')
    expect(a.viewsChangePct).toBe(100)
    expect(b.viewsChangePct).toBeNull()
    expect(b.viewsChange).toBe(50)  // prevViews=0 不影响变化值计算
  })

  // ── 3. rankState='same' 的箭头：↑升 / ↓降 / →平（diff = prevRank - currentRank）──
  it('rankState=same 时按 prevRank-currentRank 算箭头：>0→↑ / <0→↓ / =0→→', () => {
    const latest = batch([
      up(1, 'A', 100),  // currentRank=1
      up(2, 'B', 90),   // currentRank=2
      up(3, 'C', 80),   // currentRank=3
    ])
    const previous = batch([
      up(3, 'C', 800),  // prevRank=1 → C 从1降到3
      up(2, 'B', 90),   // prevRank=2 → B 持平
      up(1, 'A', 100),  // prevRank=3 → A 从3升到1
    ])

    const result = computeRankingData(latest, previous)
    const a = result.find(r => r.name === 'A')
    const b = result.find(r => r.name === 'B')
    const c = result.find(r => r.name === 'C')

    expect(a.change.arrow).toBe('↑')
    expect(a.change.diff).toBe(2)
    expect(b.change.arrow).toBe('→')
    expect(b.change.diff).toBe(0)
    expect(c.change.arrow).toBe('↓')
    expect(c.change.diff).toBe(2)
    expect([a, b, c].every(r => r.rankState === 'same')).toBe(true)
  })

  // ── 4. 新上榜：UP 在最新批但不在上一批 play_ranking → rankState='new'，viewsChange=null ──
  it('UP 不在上一批 play_ranking → rankState=new，change.isNew=true，viewsChange=null', () => {
    const latest = batch([
      up(1, '老UP', 500),   // prev=400 → +100
      up(2, '新UP', 9999),  // previous 无此 mid
    ])
    const previous = batch([up(1, '老UP', 400)])

    const result = computeRankingData(latest, previous)
    const neo = result.find(r => r.name === '新UP')

    expect(neo.rankState).toBe('new')
    expect(neo.change.isNew).toBe(true)
    expect(neo.viewsChange).toBeNull()
    expect(neo.prevRank).toBeUndefined()
    expect(neo.noPrevData).toBe(true)  // 真新上榜：prevViews 缺失
    // 新上榜 |null|=0 排在 +100 的老UP 之后
    expect(result.map(r => r.name)).toEqual(['老UP', '新UP'])
  })

  // ── 5. 排名源不可比（previous 仅 active_ranking）→ rankState='n/a'，但 viewsChange 仍可算 ──
  it('上一批无 play_ranking（仅 active_ranking）→ rankState=n/a、change=null，但 viewsChange 跨源可算', () => {
    const latest = batch([up(1, 'A', 200)])  // play_ranking
    const previous = { analysis: { active_ranking: [up(1, 'A', 150)] } }  // 无 play_ranking

    const result = computeRankingData(latest, previous)
    const a = result[0]

    expect(a.rankState).toBe('n/a')
    expect(a.change).toBeNull()
    // 播放量差值独立于排名源：total_recent_views 两侧同口径，仍可对比
    expect(a.viewsChange).toBe(50)
    expect(a.prevViews).toBe(150)
    expect(a.noPrevData).toBe(false)  // A 在 active_ranking → 有对比数据
  })

  // ── 6. latest 无 play_ranking → fallback 到 active_ranking（rankComparable 仍为 false）──
  it('latest 无 play_ranking 时 fallback 到 active_ranking；两侧非同为 play → rankState=n/a', () => {
    const latest = { analysis: { active_ranking: [up(1, 'A', 200)] } }
    const previous = batch([up(1, 'A', 150)])

    const result = computeRankingData(latest, previous)
    expect(result[0].rankState).toBe('n/a')
    expect(result[0].viewsChange).toBe(50)
  })

  // ── 7. 空数据 ──
  it('latest=null → 返回空数组', () => {
    expect(computeRankingData(null, null)).toEqual([])
  })
  it('latest.play_ranking=[] → 返回空数组', () => {
    expect(computeRankingData(batch([]), batch([up(1, 'A', 100)]))).toEqual([])
  })
  it('previous=null → 所有 UP viewsChange=null、rankState=n/a', () => {
    const result = computeRankingData(batch([up(1, 'A', 100)]), null)
    expect(result).toHaveLength(1)
    expect(result[0].viewsChange).toBeNull()
    expect(result[0].rankState).toBe('n/a')
    expect(result[0].change).toBeNull()
  })

  // ── 8. 截断 TOP10 ──
  it('latest 超过 10 个 UP → 只取前 10，changeRank 连续 1-10', () => {
    const latestList = Array.from({ length: 12 }, (_, i) => up(i + 1, `UP${i + 1}`, 100 + i))
    const prevList = Array.from({ length: 12 }, (_, i) => up(i + 1, `UP${i + 1}`, 50))
    const result = computeRankingData(batch(latestList), batch(prevList))
    expect(result).toHaveLength(10)
    expect(result.map(r => r.changeRank)).toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
  })

  // ── 9. 稳定排序：相同 |viewsChange| 保持 latestRanking 原顺序（V8 sort 稳定）──
  it('两个 UP |viewsChange| 相同 → 保持 latestRanking 原顺序', () => {
    const latest = batch([
      up(1, '先', 200),  // prev=100 → +100
      up(2, '后', 300),  // prev=200 → +100
    ])
    const previous = batch([up(1, '先', 100), up(2, '后', 200)])
    const result = computeRankingData(latest, previous)
    // 同为 +100，保持原顺序：先 在 后 之前
    expect(result.map(r => r.name)).toEqual(['先', '后'])
  })

  // ── 10. null/0 变化排最后（新上榜与无变化都排在有变化的 UP 之后）──
  it('新上榜(null)和无变化(0)排在有变化的 UP 之后；同为 0 时保持原顺序', () => {
    const latest = batch([
      up(1, '变化大', 500),  // prev=200 → +300
      up(2, '无变化', 100),  // prev=100 → 0
      up(3, '新上榜', 999),  // previous 无
    ])
    const previous = batch([up(1, '变化大', 200), up(2, '无变化', 100)])
    const result = computeRankingData(latest, previous)
    expect(result[0].name).toBe('变化大')
    expect(result.map(r => r.name).slice(1)).toEqual(['无变化', '新上榜'])
  })

  // ── 11. maxAbsChange 下限为 1（全 0 变化时防除零）──
  it('所有 UP 变化均为 0 → maxAbsChange=1（下限保护）', () => {
    const latest = batch([up(1, 'A', 100), up(2, 'B', 100)])
    const previous = batch([up(1, 'A', 100), up(2, 'B', 100)])
    const result = computeRankingData(latest, previous)
    expect(result[0].maxAbsChange).toBe(1)
  })

  // ── 12. 保留 latestRanking 原始字段（mid/face/follower_count 等透传）──
  it('结果项保留 latestRanking 的原始字段（mid 及 extra 字段透传）', () => {
    const latest = batch([up(1, 'A', 200, { face: 'f.png', follower_count: 1000 })])
    const previous = batch([up(1, 'A', 100)])
    const result = computeRankingData(latest, previous)
    expect(result[0].mid).toBe(1)
    expect(result[0].face).toBe('f.png')
    expect(result[0].follower_count).toBe(1000)
  })

  // ── 13. 排名可比但上一批不在榜的 UP：rankState='new' 且 prevViews 也为 undefined ──
  it('两侧同为 play_ranking 但 UP 上一批不在榜 → rankState=new 且 viewsChange=null', () => {
    const latest = batch([up(1, 'A', 200), up(2, 'B', 300)])
    const previous = batch([up(1, 'A', 100)])  // B 不在上一批
    const result = computeRankingData(latest, previous)
    const b = result.find(r => r.name === 'B')
    expect(b.rankState).toBe('new')
    expect(b.viewsChange).toBeNull()
    expect(b.prevViews).toBeUndefined()
    expect(b.noPrevData).toBe(true)  // 上一批不在榜 → 丢失对比数据
  })

  // ── 14. 数据源切换 + UP 不在上一批 fallback 榜 → noPrevData=true，rankState=n/a（不误判 new）──
  it('previous=active_ranking 且 UP 不在其中 → noPrevData=true, rankState=n/a（不误判 new）', () => {
    const latest = batch([up(1, 'A', 200), up(2, 'B', 300)])  // play_ranking
    const previous = { analysis: { active_ranking: [up(1, 'A', 100)] } }  // B 不在 active_ranking
    const result = computeRankingData(latest, previous)
    const a = result.find(r => r.name === 'A')
    const b = result.find(r => r.name === 'B')
    // A 在 active_ranking → 有 prevViews → noPrevData=false
    expect(a.noPrevData).toBe(false)
    expect(a.viewsChange).toBe(100)
    // B 不在 active_ranking → 丢失对比数据 → noPrevData=true，但不误判 new（rankState=n/a）
    expect(b.noPrevData).toBe(true)
    expect(b.viewsChange).toBeNull()
    expect(b.rankState).toBe('n/a')
    expect(b.change).toBeNull()
  })
})

// ═══ 组件级测试：PlayRankingChangeCard 日志诊断 ═══
// 验证 useBatchData 的 useEffect 诊断日志：数据源切换时打 warn、正常时不打。
// batches 顺序：[previous（旧）, latest（新）]；每个 batch 需带 summary.total_ups>0 才进 validBatches。
describe('PlayRankingChangeCard 日志诊断', () => {
  let warnSpy
  afterEach(() => {
    if (warnSpy) warnSpy.mockRestore()
  })

  it('两批同为 play_ranking → 不打 warn（新上榜是常态，不排查）', () => {
    warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const batches = [
      { created_at: 1700000000, analysis: { play_ranking: [up(1, 'A', 100)], summary: { total_ups: 5 } } },
      { created_at: 1700086400, analysis: { play_ranking: [up(1, 'A', 200)], summary: { total_ups: 5 } } },
    ]
    render(<PlayRankingChangeCard batches={batches} />)
    expect(warnSpy).not.toHaveBeenCalled()
  })

  it('previous 退化到 active_ranking → 打 warn 一次，含数据源 + 口径不一致信息', () => {
    warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const batches = [
      { created_at: 1700000000, analysis: { active_ranking: [up(1, 'A', 100)], summary: { total_ups: 5 } } },
      { created_at: 1700086400, analysis: { play_ranking: [up(1, 'A', 200)], summary: { total_ups: 5 } } },
    ]
    render(<PlayRankingChangeCard batches={batches} />)
    expect(warnSpy).toHaveBeenCalledTimes(1)
    const msg = warnSpy.mock.calls[0][0]
    expect(msg).toContain('[PlayRankingChange]')
    expect(msg).toContain('latest=play_ranking')
    expect(msg).toContain('previous=active_ranking')
    expect(msg).toContain('口径不一致')
    expect(msg).toContain('排名箭头降级 n/a')
  })

  it('切换且部分 UP 不在 fallback 榜 → warn 含丢失对比数据明细', () => {
    warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const batches = [
      { created_at: 1700000000, analysis: { active_ranking: [up(1, 'A', 100)], summary: { total_ups: 5 } } },
      { created_at: 1700086400, analysis: { play_ranking: [up(1, 'A', 200), up(2, 'B', 300)], summary: { total_ups: 5 } } },
    ]
    render(<PlayRankingChangeCard batches={batches} />)
    expect(warnSpy).toHaveBeenCalledTimes(1)
    const msg = warnSpy.mock.calls[0][0]
    expect(msg).toContain('丢失对比数据 1/2')
    expect(msg).toContain('B(mid=2)')
  })

  it('切换但所有 UP 都在 fallback 榜 → warn 显示 0/N 丢失', () => {
    warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const batches = [
      { created_at: 1700000000, analysis: { active_ranking: [up(1, 'A', 100), up(2, 'B', 80)], summary: { total_ups: 5 } } },
      { created_at: 1700086400, analysis: { play_ranking: [up(1, 'A', 200), up(2, 'B', 300)], summary: { total_ups: 5 } } },
    ]
    render(<PlayRankingChangeCard batches={batches} />)
    expect(warnSpy).toHaveBeenCalledTimes(1)
    expect(warnSpy.mock.calls[0][0]).toContain('丢失对比数据 0/2')
  })

  it('空 batches → 不打 warn', () => {
    warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
    render(<PlayRankingChangeCard batches={[]} />)
    expect(warnSpy).not.toHaveBeenCalled()
  })
})
