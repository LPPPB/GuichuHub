import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import VideoCard from './VideoCard'

it('uses returned radar metrics in the card layout', () => {
  render(<VideoCard
    video={{
      bvid: 'BV1demo', title: '测试视频', author: '测试UP', views: 1000,
      danmaku: 10, comments: 20, duration: 60, trend_label: '上升期',
      potential_score: 71.3,
      radar: {
        baseline_version: 'radar-v1',
        axes: [
          { id: 'reach', label: '播放规模', score: 50, raw: 1000, status: 'available' },
          { id: 'engagement', label: '互动质量', score: 50, raw: 0.04, status: 'available' },
          { id: 'discussion', label: '讨论热度', score: 50, raw: 0.02, status: 'available' },
          { id: 'spread', label: '传播能力', score: 50, raw: 0.01, status: 'available' },
          { id: 'momentum', label: '增长动能', score: 50, raw: 50, status: 'available' },
          { id: 'live', label: '实时关注', score: 50, raw: 10, status: 'available' },
        ],
      },
    }}
    index={0}
    formatNumber={(value) => String(value)}
  />)

  expect(screen.getAllByRole('img', { name: '视频数据雷达图' })).toHaveLength(2)
})
