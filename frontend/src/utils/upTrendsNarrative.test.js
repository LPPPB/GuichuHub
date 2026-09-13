import { describe, expect, it } from 'vitest'
import { buildUpTrendsNarrative } from './upTrendsNarrative'

describe('buildUpTrendsNarrative', () => {
  it('把观测规模与近 7 天核心指标整理成一条可扫读的页面结论', () => {
    const result = buildUpTrendsNarrative({
      total_ups: 139,
      pool_total_videos: 86,
      pool_total_views: 2_500_000,
      pool_avg_views_per_video: 29_070,
    }, (value) => ({ 2500000: '250万', 29070: '2.9万' })[value] || String(value))

    expect(result).toEqual({
      eyebrow: 'CREATOR PULSE · 近 7 天全量观测',
      headline: '139 位 UP 主正在形成最近 7 天的创作脉搏',
      detail: '共收录 86 部视频 · 累计播放 250万 · 单条平均 2.9万',
    })
  })

  it('缺少播放指标时只展示可信的观测规模，不拼接空数据', () => {
    expect(buildUpTrendsNarrative({ total_ups: 12 }, String)).toEqual({
      eyebrow: 'CREATOR PULSE · 近 7 天全量观测',
      headline: '12 位 UP 主正在形成最近 7 天的创作脉搏',
      detail: '持续追踪公开动态，新的投稿与播放变化会在下次分析后更新',
    })
  })
})
