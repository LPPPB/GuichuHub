import { fireEvent, render, screen, within } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { api } from '../utils/api'
import VideoCard from './VideoCard'

const video = {
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
}

it('hides radar in a video card unless its ranking page enables it', () => {
  render(<VideoCard video={video} index={0} formatNumber={String} />)

  expect(screen.queryByRole('img', { name: '视频数据雷达图' })).not.toBeInTheDocument()
})

it('renders one radar for a video ranking card', () => {
  render(<VideoCard video={video} index={0} formatNumber={String} showRadar />)

  expect(screen.getAllByRole('img', { name: '视频数据雷达图' })).toHaveLength(1)
})

it('shows author metadata and falls back cleanly after an avatar fails', () => {
  const { container } = render(<VideoCard video={{ ...video, author_avatar: 'https://i0.hdslb.com/avatar.jpg', pub_date: 1700000000, tname: '鬼畜剧场' }} formatNumber={String} />)
  expect(screen.getByText('2023-11-15 06:13')).toHaveAttribute('datetime', '2023-11-14T22:13:20.000Z')
  expect(screen.getByText('鬼畜剧场')).toBeVisible()
  expect(screen.queryByText(/UP主 ·/)).not.toBeInTheDocument()
  const avatar = container.querySelector('.video-card-avatar img')
  expect(avatar).toHaveAttribute('src', '/api/proxy/image?url=https%3A%2F%2Fi0.hdslb.com%2Favatar.jpg')
  fireEvent.error(avatar)
  expect(container.querySelector('.video-card-avatar img')).toBeNull()
  expect(screen.getByText('测试UP')).toBeVisible()
})

it('distinguishes historical online observations from live counts including zero', () => {
  const { rerender } = render(<VideoCard video={{ ...video, online_count: 454, online_circuit_skipped: true }} formatNumber={String} />)
  expect(screen.getByText('最近观测 454人')).toBeVisible()
  expect(screen.queryByText(/人正在看/)).not.toBeInTheDocument()
  rerender(<VideoCard video={{ ...video, online_count: 0 }} formatNumber={String} />)
  expect(screen.getByText('0人正在看')).toBeVisible()
  rerender(<VideoCard video={{ ...video, online_count: null }} formatNumber={String} />)
  expect(screen.queryByText(/人正在看/)).not.toBeInTheDocument()
})

it('opens and closes an observation panel without nesting controls in a video link', async () => {
  const request = vi.spyOn(api, 'getVideoObsTrend').mockResolvedValue({ success: true, data: { points: [] } })
  try {
    render(<VideoCard video={video} formatNumber={String} />)
    const button = screen.getByRole('button', { name: '观测趋势' })
    expect(button.closest('a')).toBeNull()
    fireEvent.click(button)
    const close = await screen.findByRole('button', { name: '收起趋势' })
    expect(close).toHaveAttribute('aria-expanded', 'true')
    const panel = document.getElementById(close.getAttribute('aria-controls'))
    expect(panel).toBeInTheDocument()
    await within(panel).findByText(/数据积累中/)
    expect(request).toHaveBeenCalledWith('BV1demo', 48)
    fireEvent.click(close)
    expect(panel).not.toBeInTheDocument()
  } finally {
    request.mockRestore()
  }
})
