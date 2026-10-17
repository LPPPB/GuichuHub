import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'
import { api } from './utils/api'
import App from './App'

vi.mock('./utils/api', () => ({
  verifyAdminSilent: vi.fn().mockResolvedValue(false),
  api: {
    getDashboard: vi.fn(),
    getFavorites: vi.fn().mockResolvedValue({ success: true, data: [] }),
    getAuthMe: vi.fn().mockResolvedValue({ success: true, data: { admin: false, user: null } }),
    getStatus: vi.fn().mockResolvedValue({ success: true, data: { crawling: false } }),
    getInteractionQuality: vi.fn().mockResolvedValue({ success: true, data: [] }),
    getTagHeat: vi.fn().mockResolvedValue({ success: true, data: [] }),
    getRisingWords: vi.fn().mockResolvedValue({ success: true, data: [], meta: null }),
    getBurstingVideos: vi.fn().mockResolvedValue({ success: true, data: { videos: [] } }),
    getVideoObsTrend: vi.fn().mockResolvedValue({ success: true, data: { points: [] } }),
  },
}))

const videos = Array.from({ length: 7 }, (_, i) => ({
  bvid: `BVsummary${i + 1}`, title: `摘要测试视频 ${i + 1}`, author: `测试 UP ${i + 1}`,
  cover: 'https://i0.hdslb.com/cover.jpg', views: 10000, likes: 500,
  potential_score: 70, potential_reason: '互动爆款', description: '视频介绍',
}))

beforeEach(() => {
  localStorage.setItem('kb-theme', 'light')
  vi.spyOn(window, 'scrollTo').mockImplementation(() => {})
  api.getDashboard.mockResolvedValue({ success: true, data: { kichu_rank: videos } })
})

it('preserves the card information, moves reasons and trend into the body, and opens the complete ranking', async () => {
  const user = userEvent.setup()
  render(<App />)
  const heading = await screen.findByRole('heading', { name: '鬼畜区排行榜', exact: true })
  const summary = within(heading.closest('section'))
  expect(summary.getAllByRole('link', { name: /^摘要测试视频/ }).map(link => link.textContent))
    .toEqual(['摘要测试视频 1', '摘要测试视频 2', '摘要测试视频 3', '摘要测试视频 4', '摘要测试视频 5'])
  expect(summary.queryByText('摘要测试视频 6')).not.toBeInTheDocument()
  expect(summary.getByRole('link', { name: '摘要测试视频 1' }))
    .toHaveAttribute('href', 'https://www.bilibili.com/video/BVsummary1')
  expect(summary.getByText('测试 UP 1')).toBeVisible()
  expect(summary.getAllByText('5.0%')).toHaveLength(5)
  expect(summary.queryByRole('button', { name: '收藏', exact: true })).not.toBeInTheDocument()
  expect(summary.queryByRole('button', { name: 'AI 总结' })).not.toBeInTheDocument()
  expect(summary.getAllByText('视频介绍')).toHaveLength(5)
  expect(summary.getAllByText('· 互动爆款')).toHaveLength(5)
  const firstCard = summary.getByRole('link', { name: '摘要测试视频 1' }).closest('article')
  expect(firstCard.querySelector('.video-card-footer')).toBeNull()
  const body = within(firstCard.querySelector('.video-card-layout'))
  expect(body.getByText('· 互动爆款')).toBeVisible()
  await user.click(body.getByRole('button', { name: '观测趋势' }))
  expect(await within(firstCard).findByText(/数据积累中/)).toBeVisible()
  await user.click(body.getByRole('button', { name: '收起趋势' }))
  expect(within(firstCard).queryByText(/数据积累中/)).not.toBeInTheDocument()
  await user.click(summary.getByRole('button', { name: '查看全部 →' }))
  expect(await screen.findByRole('heading', { level: 1, name: '鬼畜区排行榜' })).toBeVisible()
  expect(screen.getByRole('link', { name: '摘要测试视频 7' })).toBeVisible()
  expect(screen.getAllByRole('button', { name: '观测趋势' })).toHaveLength(7)
})

it('keeps unknown metrics distinct from zero in a short ranking', async () => {
  api.getDashboard.mockResolvedValue({ success: true, data: { kichu_rank: [
    { ...videos[0], views: null, likes: null },
    { ...videos[1], views: 10000, likes: 0 },
  ] } })
  render(<App />)
  const heading = await screen.findByRole('heading', { name: '鬼畜区排行榜', exact: true })
  const summary = within(heading.closest('section'))
  const unknownCard = summary.getByRole('link', { name: '摘要测试视频 1' }).closest('article')
  expect(unknownCard).not.toBeNull()
  expect(unknownCard.querySelector('.video-card-views strong')).toHaveTextContent('—')
  expect(summary.getByText('0.0%')).toBeVisible()
  expect(summary.getAllByRole('link', { name: /^摘要测试视频/ })).toHaveLength(2)
})
