import { it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react'
import UpRequestModal from './UpRequestModal'
import { api } from '../utils/api'

vi.mock('../utils/api', () => ({ api: {
  getObservationRoster: vi.fn(), submitUpRequest: vi.fn(), getMyUpRequests: vi.fn(),
} }))
afterEach(() => { cleanup(); vi.clearAllMocks() })

it('从公开名单选择停止观测，必须填写原因并发送 remove 类型', async () => {
  api.getObservationRoster.mockResolvedValue({ success: true, data: { total: 1, ups: [{ mid: 101, name: '测试UP' }] } })
  api.submitUpRequest.mockResolvedValue({ success: true })
  api.getMyUpRequests.mockResolvedValue({ success: true, data: { pending: [], processed: [] } })
  render(<UpRequestModal initialTab="roster" onClose={() => {}} />)
  const moreButton = await screen.findByRole('button', { name: '测试UP的更多操作' })
  expect(screen.queryByRole('menuitem', { name: '申请停止观测' })).not.toBeInTheDocument()
  fireEvent.click(moreButton)
  expect(screen.getByRole('menuitem', { name: '查看主页' })).toHaveAttribute('href', 'https://space.bilibili.com/101')
  fireEvent.click(screen.getByRole('menuitem', { name: '申请停止观测' }))
  expect(screen.getByText('提交停止申请').disabled).toBe(true)
  fireEvent.change(screen.getByLabelText('停止观测原因'), { target: { value: '不符合主题' } })
  fireEvent.click(screen.getByText('提交停止申请'))
  await waitFor(() => expect(api.submitUpRequest).toHaveBeenCalledWith(101, '不符合主题', 'remove'))
})

it('名单读取失败可见，用户可重试', async () => {
  api.getObservationRoster.mockResolvedValue({ success: false, message: '服务暂不可用' })
  render(<UpRequestModal initialTab="roster" onClose={() => {}} />)
  expect(await screen.findByRole('alert')).toHaveTextContent('服务暂不可用')
  fireEvent.click(screen.getByText('刷新名单'))
  await waitFor(() => expect(api.getObservationRoster).toHaveBeenCalledTimes(2))
})

it('切换标签页时保持同一个固定高度窗体', async () => {
  api.getObservationRoster.mockResolvedValue({ success: true, data: { total: 0, ups: [] } })
  render(<UpRequestModal initialTab="search" onClose={() => {}} />)

  const modal = document.querySelector('.max-w-lg')
  expect(modal).toHaveClass('h-[760px]', 'max-h-[85vh]')

  fireEvent.click(screen.getByText('当前名单'))
  await screen.findByText('当前观测名单 · 0 位')
  expect(document.querySelector('.max-w-lg')).toBe(modal)
})
