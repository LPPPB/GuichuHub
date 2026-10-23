import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import InteractionQualityCard from './InteractionQualityCard'

const video = {
  bvid: 'BV1test', title: '测试宝藏视频', author: '测试UP', tname: '鬼畜调教', views: 12345,
  coin_ratio: 2.13, like_ratio: 8.42, fav_ratio: 3.51,
  engagement_score: 72.5, is_treasure: true,
}

it('shows Bilibili-style coin and like metrics alongside the relative score on the whole-card link', () => {
  render(<InteractionQualityCard video={video} rank={1} formatNumber={n => String(n)} />)
  const link = screen.getByRole('link')
  expect(link).toHaveAttribute('href', 'https://www.bilibili.com/video/BV1test')
  expect(link).toHaveTextContent('投币2.13%')
  expect(link).toHaveTextContent('点赞8.42%')
  expect(link).toHaveTextContent('收藏3.51%')
  expect(link).toHaveTextContent('互动相对分72.50')
  expect(link).toHaveTextContent('宝藏')
})

it('keeps the pending score explicit when the radar baseline is unavailable', () => {
  render(<InteractionQualityCard video={{ ...video, engagement_score: null, score_reason: '参考不足', is_treasure: false }}
                                 rank={2} formatNumber={n => String(n)} />)
  expect(screen.getByText('待评分')).toBeInTheDocument()
  expect(screen.getByTitle('参考不足')).toBeInTheDocument()
  expect(screen.queryByText('宝藏')).not.toBeInTheDocument()
})
