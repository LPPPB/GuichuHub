import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import App from './App'

vi.mock('./utils/api', () => ({
  verifyAdminSilent: vi.fn().mockResolvedValue(false),
  api: {
    getDashboard: vi.fn().mockResolvedValue({ success: true, data: {} }),
    getFavorites: vi.fn().mockResolvedValue({ success: true, data: [] }),
    getAuthMe: vi.fn().mockResolvedValue({ success: true, data: { admin: false, user: null } }),
    getStatus: vi.fn().mockResolvedValue({ success: true, data: { crawling: false } }),
    getInteractionQuality: vi.fn().mockResolvedValue({ success: true, data: [] }),
    getTagHeat: vi.fn().mockResolvedValue({ success: true, data: [] }),
    getRisingWords: vi.fn().mockResolvedValue({ success: true, data: [], meta: null }),
    getQrcode: vi.fn().mockResolvedValue({ success: false, message: '测试环境' }),
  },
}))

beforeEach(() => {
  localStorage.setItem('kb-theme', 'dark')
  vi.spyOn(window, 'scrollTo').mockImplementation(() => {})
})
afterEach(() => vi.restoreAllMocks())

it('shows the four requested partner destinations as safe external links', () => {
  render(<App />)
  const footer = within(screen.getByRole('contentinfo'))
  const links = [
    ['Hajimi Web', 'https://www.hajimi.world/'],
    ['哈基米文化', 'https://cul.hajimi.world/'],
    ['基米天堂', 'https://hachimi.world/'],
    ['哈基哈米', 'https://hajihami.com/'],
  ]
  for (const [name, href] of links) {
    const link = footer.getByRole('link', { name })
    expect(link).toHaveAttribute('href', href)
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
  }
})

it('navigates to an existing dashboard tab without inventing a route', async () => {
  const user = userEvent.setup()
  render(<App />)
  expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
  expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('GuichuHub')
  const footer = within(screen.getByRole('contentinfo'))
  await user.click(footer.getByRole('button', { name: '热梗' }))
  expect(await screen.findByRole('heading', { name: '热梗库' })).toBeInTheDocument()
  expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
})

it('moves focus from the navigation drawer into the login panel', async () => {
  const user = userEvent.setup()
  render(<App />)
  await user.click(screen.getByRole('button', { name: '打开导航菜单' }))
  await user.click(within(screen.getByRole('dialog', { name: '站点导航' })).getByRole('button', { name: 'B 站账号登录' }))
  expect(screen.queryByRole('dialog', { name: '站点导航' })).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: '关闭登录' })).toHaveFocus()
})

it('keeps the ICP link and displays the approved public security filing as a safe query link', () => {
  vi.spyOn(Date.prototype, 'getFullYear').mockReturnValue(2031)
  render(<App />)
  const footer = within(screen.getByRole('contentinfo'))
  expect(footer.getByText(/© 2031 GuichuHub/)).toBeInTheDocument()
  expect(footer.getByRole('link', { name: '苏ICP备2026075438号-1' })).toHaveAttribute('href', 'https://beian.miit.gov.cn/')
  const publicSecurity = footer.getByRole('link', { name: '豫公网安备41010502008078号' })
  expect(publicSecurity).toHaveAttribute('href', 'https://beian.mps.gov.cn/#/query/webSearch?code=41010502008078')
  expect(publicSecurity).toHaveAttribute('target', '_blank')
  expect(publicSecurity).toHaveAttribute('rel', 'noopener noreferrer')
  expect(publicSecurity.querySelector('img')).toHaveAttribute('src', '/images/public-security-filing.png')
  expect(footer.queryByText('公安联网备案审核中')).not.toBeInTheDocument()
})
