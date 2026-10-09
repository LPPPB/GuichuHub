import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
vi.mock('./EChart', () => ({ default: () => null }))
vi.mock('../utils/api', () => ({ api: { getActiveCalendarJob: vi.fn(), getCalendarJob: vi.fn(), retryCalendarJob: vi.fn(), calendarBackfill: vi.fn() } }))
import { api } from '../utils/api'
import { PublishCalendarCard } from './TrendCharts'
const failed = { id: 'old', status: 'failed', total_ups: 1, processed_ups: 1, failed_ups: 1, partial_ups: 0 }
beforeEach(() => {
  vi.useFakeTimers(); vi.resetAllMocks()
  api.getActiveCalendarJob.mockResolvedValueOnce({ success: true, data: { ...failed, status: 'running' } }).mockResolvedValue({ success: true, data: null })
  api.getCalendarJob.mockResolvedValue({ success: true, data: failed })
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ success: true, data: {} }) }))
})
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.useRealTimers() })
describe('calendar retry protocol', () => {
  it('shows remaining cooldown seconds', async () => {
    api.retryCalendarJob.mockResolvedValue({ success: false, retry_after: 37, message: '请稍后重试' })
    await act(async () => { render(<PublishCalendarCard isAdmin />) })
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: '重试失败项' })) })
    expect(screen.getByText('请等待 37 秒后重试')).toBeVisible()
  })
  it('takes over an existing retry instead of keeping the old failure', async () => {
    api.retryCalendarJob.mockResolvedValue({ success: false, busy: true, job_id: 'new', data: { ...failed, id: 'new', status: 'queued' } })
    await act(async () => { render(<PublishCalendarCard isAdmin />) })
    api.getCalendarJob.mockResolvedValue({ success: true, data: { ...failed, id: 'new', status: 'running', progress_percent: 0, processed_ups: 0 } })
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: '重试失败项' })) })
    expect(api.getCalendarJob).toHaveBeenCalledWith('new')
    expect(screen.getByText('回填中 0/1（0%）')).toBeVisible()
  })
})
