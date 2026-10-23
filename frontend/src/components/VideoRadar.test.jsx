import { fireEvent, render, screen } from '@testing-library/react'
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
  render(<VideoRadar radar={radar} />)

  const chart = screen.getByRole('img', { name: '视频数据雷达图' })
  expect(chart).toBeInTheDocument()
  expect(chart).not.toHaveTextContent('潜力')
  expect(chart).not.toHaveTextContent('71.3')
  expect(screen.getAllByText('实时关注：暂无实时观测').length).toBeGreaterThan(0)
})

it('gives every radar a distinct SVG gradient definition', () => {
  render(<><VideoRadar radar={radar} /><VideoRadar radar={radar} /></>)

  const ids = [...document.querySelectorAll('linearGradient')].map(node => node.id)
  expect(new Set(ids).size).toBe(2)
})

it('renders unavailable live attention as an incomplete shape instead of a zero-score vertex', () => {
  render(<VideoRadar radar={radar} />)

  expect(document.querySelector('polygon[fill^="url("]')).toBeNull()
  expect(screen.getByText(/播放规模：224,000；互动质量：6.70%/)).toBeInTheDocument()
})

const v2 = {
  algorithm_version: 'radar-v2', baseline_version: 'radar-v2-bootstrap-demo', observed_at: 1700000000,
  axes: [
    ['reach', '播放规模'], ['approval', '观众认可'], ['retention', '收藏倾向'],
    ['discussion', '讨论活跃'], ['sharing', '分享倾向'], ['growth', '近期增速'],
  ].map(([id, label]) => ({ id, label, score: 50, raw: 12, unit: '次/千播放', status: 'available',
    components: [{ id: 'likes_rate', label: '点赞', raw: 12, score: 50,
      reference: { count: 240, age_min_days: 0, age_max_days: 7 } },
      ...(id === 'approval' ? [{ id: 'coins_rate', label: '投币', raw: 2, score: 50 }] : [])] })),
}

it('opens a keyboard and touch accessible axis explanation and closes on Escape', () => {
  const data = structuredClone(v2)
  data.axes[1].components[0].score = 20
  data.axes[1].components[1].score = 80
  render(<VideoRadar radar={data} />)
  fireEvent.click(screen.getByRole('button', { name: '观众认可详情' }))
  expect(screen.getByRole('dialog', { name: '观众认可' })).toBeVisible()
  expect(screen.getByText('12 次/千播放')).toBeVisible()
  expect(screen.getByText(/综合相对分/)).toBeVisible()
  expect(screen.getByRole('dialog')).toHaveTextContent('分位 20分')
  expect(screen.getByRole('dialog')).toHaveTextContent('分位 80分')
  fireEvent.keyDown(document, { key: 'Escape' })
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
})

it('shows missing reasons and draws a real zero at the center without filling missing axes', () => {
  const data = structuredClone(v2)
  data.axes[0].score = 0
  data.axes[1] = { ...data.axes[1], score: null, status: 'insufficient_baseline', reason: '参考样本不足' }
  data.axes[2] = { ...data.axes[2], score: null, status: 'stale', reason: '观测已过期' }
  render(<VideoRadar radar={data} />)
  expect(document.querySelector('[data-testid="radar-data-polygon"]')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '观众认可详情' }))
  expect(screen.getByRole('dialog')).toHaveTextContent('参考样本不足')
  expect(screen.getByText('相对站内观测样本')).toBeVisible()
})

it('scales the chart and axis hit areas together for a larger demo preview', () => {
  render(<VideoRadar radar={v2} size={280} />)
  const chart = screen.getByRole('img', { name: '视频数据雷达图' })
  expect(chart).toHaveStyle({ height: '280px' })
  const hit = screen.getByRole('button', { name: '播放规模详情' })
  expect(parseFloat(hit.style.top)).toBeCloseTo(14 / 164 * 280)
  fireEvent.click(hit)
  expect(screen.getByRole('dialog', { name: '播放规模' })).toBeVisible()
})
