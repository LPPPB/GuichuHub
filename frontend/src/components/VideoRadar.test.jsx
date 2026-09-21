import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import VideoRadar from './VideoRadar'

const radar = {
  baseline_version: 'radar-v1',
  axes: [
    { id: 'reach', label: '播放规模', score: 68, raw: 224000, status: 'available' },
    { id: 'engagement', label: '互动质量', score: 84, raw: 0.067, status: 'available' },
    { id: 'discussion', label: '讨论热度', score: 71, raw: 0.031, status: 'available' },
    { id: 'spread', label: '传播能力', score: 62, raw: 0.012, status: 'available' },
    { id: 'momentum', label: '增长动能', score: 75, raw: 75, status: 'available' },
    { id: 'live', label: '实时关注', score: null, raw: null, status: 'historical' },
  ],
}

it('renders an accessible radar and makes unavailable live data explicit', () => {
  render(<VideoRadar radar={radar} potentialScore={71.3} />)

  expect(screen.getByRole('img', { name: '视频数据雷达图' })).toBeInTheDocument()
  expect(screen.getByText('潜力')).toBeInTheDocument()
  expect(screen.getByText('71.3')).toBeInTheDocument()
  expect(screen.getAllByText('实时关注：暂无实时观测').length).toBeGreaterThan(0)
})

it('gives every radar a distinct SVG gradient definition', () => {
  render(<><VideoRadar radar={radar} potentialScore={70} /><VideoRadar radar={radar} potentialScore={71} /></>)

  const ids = [...document.querySelectorAll('linearGradient')].map(node => node.id)
  expect(new Set(ids).size).toBe(2)
})

it('renders unavailable live attention as an incomplete shape instead of a zero-score vertex', () => {
  render(<VideoRadar radar={radar} potentialScore={71.3} />)

  expect(document.querySelector('polygon[fill^="url("]')).toBeNull()
  expect(screen.getByText(/播放规模：224,000；互动质量：6.70%/)).toBeInTheDocument()
})
