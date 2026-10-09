import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'

vi.mock('./EChart', () => ({ default: () => null }))
vi.mock('../utils/api', () => ({ api: {
  getPublishHabits: vi.fn(), getFollowerGrowth: vi.fn(), getUpTrendsHotGrowth: vi.fn(),
  getCalendarRecent: vi.fn(), upTrendsCheck: vi.fn(), upTrendsAnalysis: vi.fn(),
  upTrendsHistory: vi.fn(), upTrendsProgress: vi.fn(), upTrendsRefresh: vi.fn(),
  getActiveCalendarJob: vi.fn(),
} }))
import { api } from '../utils/api'
import UpTrends from './UpTrends'

const analysis = (count = 1) => ({ success: true, data: {
  created_at: 1_790_000_000, tracked_up_count: count, up_details: [],
  analysis: { summary: { total_ups: count, pool_total_videos: 1, pool_total_views: 101, pool_avg_views_per_video: 101 } },
} })
const progress = (status, extra = {}) => ({ success: true, data: {
  task_id: 'active-task', status, current: 0, total: 1,
  current_up: status === 'queued' ? '等待 Worker 执行' : '测试UP', eta_seconds: 0,
  done: ['succeeded', 'partial', 'failed'].includes(status),
  error: null, warnings: [], worker_unavailable: false, ...extra,
} })

beforeEach(() => {
  vi.useFakeTimers()
  vi.resetAllMocks()
  for (const method of ['getPublishHabits', 'getFollowerGrowth', 'getUpTrendsHotGrowth', 'getCalendarRecent']) {
    api[method].mockResolvedValue({ success: false })
  }
  api.upTrendsCheck.mockResolvedValue({ success: true, has_list: true, active_task_id: null })
  api.upTrendsAnalysis.mockResolvedValue(analysis())
  api.upTrendsHistory.mockResolvedValue({ success: true, data: { batches: [] } })
  api.upTrendsRefresh.mockResolvedValue({ success: true, task_id: 'active-task' })
  api.upTrendsProgress.mockResolvedValue(progress('queued'))
  api.getActiveCalendarJob.mockResolvedValue({ success: true, data: null })
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ success: true, data: {}, meta: {} }) }))
})
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.useRealTimers() })
async function mount() {
  let view
  await act(async () => { view = render(<UpTrends formatNumber={String} isAdmin />) })
  return view
}
async function refresh() {
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: '刷新动态' })) })
}

describe('durable analysis jobs', () => {
  it('rejoins the active task on page entry', async () => {
    api.upTrendsCheck.mockResolvedValue({ success: true, has_list: true, active_task_id: 'active-task' })
    await mount()
    expect(screen.getByText('等待 Worker 执行')).toBeVisible()
    expect(api.upTrendsRefresh).not.toHaveBeenCalled()
  })
  it('takes over a busy task instead of starting again', async () => {
    api.upTrendsRefresh.mockResolvedValue({ success: false, busy: true, task_id: 'active-task' })
    await mount(); await refresh()
    expect(screen.getByText('等待 Worker 执行')).toBeVisible()
    expect(api.upTrendsProgress).toHaveBeenCalledWith('active-task')
  })
  it('reloads saved analysis on success without progress.result', async () => {
    api.upTrendsAnalysis.mockResolvedValueOnce(analysis()).mockResolvedValue(analysis(2))
    api.upTrendsProgress.mockResolvedValue(progress('succeeded'))
    await mount(); await refresh()
    expect(screen.getByText('观测 2 位 UP 主')).toBeVisible()
    expect(screen.getByRole('button', { name: '刷新动态' })).toBeEnabled()
  })
  it('loads saved data and shows partial followup failure', async () => {
    api.upTrendsAnalysis.mockResolvedValueOnce(analysis()).mockResolvedValue(analysis(2))
    api.upTrendsProgress.mockResolvedValue(progress('partial', {
      warnings: [{ code: 'calendar_enqueue_failed', message: '观测已保存，日历任务提交失败' }],
      error: { code: 'calendar_enqueue_failed', message: '观测已保存，日历任务提交失败' },
    }))
    await mount(); await refresh()
    expect(screen.getByText('观测已保存，日历任务提交失败')).toBeVisible()
    expect(screen.getByText('观测 2 位 UP 主')).toBeVisible()
  })
  it('keeps previous data on failed core save', async () => {
    api.upTrendsProgress.mockResolvedValue(progress('failed', { error: { code: 'core_save_failed', message: '观测保存失败' } }))
    await mount(); await refresh()
    expect(screen.getByText('观测保存失败')).toBeVisible()
    expect(screen.getByText('数据在线')).toBeVisible()
  })
  it('ends refreshing immediately when task does not exist', async () => {
    api.upTrendsProgress.mockResolvedValue({ success: false, code: 'task_not_found', message: '任务不存在' })
    await mount(); await refresh()
    expect(screen.getByText('任务不存在')).toBeVisible()
    expect(screen.getByRole('button', { name: '刷新动态' })).toBeEnabled()
  })
  it('stops after three consecutive network failures and offers reconnect', async () => {
    api.upTrendsProgress.mockResolvedValue({ success: false, message: '连接中断' })
    await mount(); await refresh()
    await act(async () => { await vi.advanceTimersByTimeAsync(7000) })
    expect(screen.getByText(/连接中断/)).toBeVisible()
    expect(screen.getByRole('button', { name: '重新连接' })).toBeEnabled()
    expect(api.upTrendsProgress).toHaveBeenCalledTimes(3)
  })
  it('pauses when Worker is unavailable without losing task identity', async () => {
    api.upTrendsProgress.mockResolvedValue(progress('queued', { worker_unavailable: true }))
    await mount(); await refresh()
    expect(screen.getByText(/Worker 暂不可用/)).toBeVisible()
    expect(screen.getByRole('button', { name: '重新连接' })).toBeEnabled()
    await act(async () => { await vi.advanceTimersByTimeAsync(5000) })
    expect(api.upTrendsProgress).toHaveBeenCalledTimes(1)
  })
  it('cancels future polling on unmount', async () => {
    const view = await mount(); await refresh()
    const calls = api.upTrendsProgress.mock.calls.length
    view.unmount()
    await act(async () => { await vi.advanceTimersByTimeAsync(3000) })
    expect(api.upTrendsProgress).toHaveBeenCalledTimes(calls)
  })
})
