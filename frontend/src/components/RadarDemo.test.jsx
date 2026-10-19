import { fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import RadarDemo from './RadarDemo'
import DemoCenter from './DemoCenter'

vi.mock('./ObsTrendChart', () => ({ default: () => <div>观测图表样例</div> }))
vi.mock('./TrendCharts', () => ({ PlayRankingChangeCard: () => <div>排行图表样例</div> }))
afterEach(() => vi.unstubAllGlobals())

it('opens the radar from the demo center without calling a backend', () => {
  const request = vi.fn()
  vi.stubGlobal('fetch', request)
  render(<DemoCenter />)
  fireEvent.click(screen.getByRole('button', { name: '视频雷达图', exact: true }))
  expect(screen.getByRole('img', { name: '视频数据雷达图' })).toBeVisible()
  expect(screen.getByText('样例 3/3 · radar-v2')).toBeVisible()
  expect(screen.getAllByRole('slider')).toHaveLength(6)
  expect(request).not.toHaveBeenCalled()
})

it('distinguishes missing and expired observations from a measured zero', () => {
  render(<RadarDemo />)
  fireEvent.click(screen.getByRole('button', { name: '样本不足', exact: true }))
  expect(screen.queryByTestId('radar-data-polygon')).not.toBeInTheDocument()
  expect(screen.getByTestId('radar-data-line')).toBeInTheDocument()
  expect(screen.getByRole('slider', { name: '收藏倾向' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: '收藏倾向详情' }))
  expect(screen.getByRole('dialog')).toHaveTextContent('参考样本不足')
  fireEvent.click(screen.getByRole('button', { name: '观测过期', exact: true }))
  fireEvent.click(screen.getByRole('button', { name: '近期增速详情' }))
  expect(screen.getByRole('dialog')).toHaveTextContent('观测已过期')
  fireEvent.click(screen.getByRole('button', { name: '真实零分', exact: true }))
  expect(screen.getByRole('slider', { name: '近期增速' })).toHaveValue('0')
  expect(screen.getByRole('slider', { name: '近期增速' })).toBeEnabled()
  expect(screen.getByTestId('radar-data-polygon')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '近期增速详情' }))
  expect(screen.getByRole('dialog')).toHaveTextContent('近期增速 · 0分')
  expect(screen.getByRole('dialog')).toHaveTextContent('新增 0 播放')
})

it('adjusts an axis, preserves it during replay and restores the selected preset on reset', () => {
  render(<RadarDemo />)
  fireEvent.click(screen.getByRole('button', { name: '互动突出', exact: true }))
  fireEvent.change(screen.getByRole('slider', { name: '观众认可' }), { target: { value: '25' } })
  fireEvent.click(screen.getByRole('button', { name: '观众认可详情' }))
  expect(screen.getByRole('dialog')).toHaveTextContent('观众认可 · 25分')
  expect(within(screen.getByRole('dialog')).getAllByText('分位 25分')).toHaveLength(2)
  const chart = screen.getByRole('img', { name: '视频数据雷达图' })
  fireEvent.click(screen.getByRole('button', { name: '重播展开动画' }))
  expect(chart).not.toBeInTheDocument()
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(screen.getByRole('slider', { name: '观众认可' })).toHaveValue('25')
  fireEvent.click(screen.getByRole('button', { name: '重置样例' }))
  expect(screen.getByRole('slider', { name: '观众认可' })).toHaveValue('91')
})

it('honors reduced motion by immediately rendering the final shape', () => {
  vi.stubGlobal('matchMedia', () => ({ matches: true }))
  render(<RadarDemo />)
  const points = screen.getByTestId('radar-data-polygon').getAttribute('points')
  expect(points).not.toContain('82.00,82.00')
  fireEvent.click(screen.getByRole('button', { name: '重播展开动画' }))
  expect(screen.getByTestId('radar-data-polygon')).toHaveAttribute('points', points)
})
