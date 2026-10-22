import { render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import BilibiliLogin from './BilibiliLogin'
import { api } from '../utils/api'

vi.mock('../utils/api', () => ({ api: {
  getQrcode: vi.fn(async () => ({ success: false })),
  collectLogin: vi.fn(async () => ({ success: false })),
} }))

it.each(['identity', 'collect'])('never starts a retired %s QR login', mode => {
  render(<BilibiliLogin mode={mode} onClose={() => {}} />)
  expect(screen.getByText('B站登录已下线')).toBeVisible()
  expect(screen.queryByRole('img', { name: 'B站登录二维码' })).not.toBeInTheDocument()
  expect(api.getQrcode).not.toHaveBeenCalled()
  expect(api.collectLogin).not.toHaveBeenCalled()
})
