import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

vi.mock('./EChart', () => ({ default: () => null }))
vi.mock('../utils/api', () => ({
  api: {
    getPublishHabits: vi.fn().mockResolvedValue({ success: false }),
    getFollowerGrowth: vi.fn().mockResolvedValue({ success: false }),
    getUpTrendsHotGrowth: vi.fn().mockResolvedValue({ success: false }),
    getCalendarRecent: vi.fn().mockResolvedValue({ success: false }),
    upTrendsCheck: vi.fn().mockResolvedValue({ has_list: true }),
    upTrendsAnalysis: vi.fn().mockResolvedValue({
      success: true,
      data: {
        created_at: 1_780_000_000,
        tracked_up_count: 1,
        up_details: [],
        analysis: {
          summary: {
            total_ups: 1,
            pool_total_videos: 2,
            pool_total_views: 300,
            pool_avg_views_per_video: 150,
          },
        },
      },
    }),
    upTrendsHistory: vi.fn().mockResolvedValue({ success: true, data: { batches: [] } }),
  },
}))

import UpTrends from './UpTrends'

describe('UP 主动态页面表面层级', () => {
  it('环境装饰被限制在首屏卡片内部，不在页面根节点另铺一层背景', async () => {
    render(<UpTrends formatNumber={String} isAdmin={false} />)

    const heading = await screen.findByRole('heading', { name: 'UP主动态' })
    const header = heading.closest('section')
    const pageRoot = header.parentElement
    const pageLevelDecorations = [...pageRoot.children]
      .filter((element) => element !== header && element.getAttribute('aria-hidden') === 'true')

    expect(pageLevelDecorations).toHaveLength(0)
  })
})
