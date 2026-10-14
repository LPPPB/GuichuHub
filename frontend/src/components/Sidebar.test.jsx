import { useState } from 'react'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { Flame, Layers, TrendingUp, Trophy, Zap } from 'lucide-react'
import Sidebar from './Sidebar'

const groups = [
  { id: 'home', label: '仪表盘', icon: TrendingUp, tabs: [{ id: 'dashboard', label: '总览', icon: TrendingUp }] },
  { id: 'trends', label: '内容趋势', icon: Flame, tabs: [
    { id: 'kichu-rank', label: '鬼畜榜', icon: Trophy },
    { id: 'memes', label: '热梗', icon: Flame },
    { id: 'videos', label: '潜力视频', icon: Zap },
  ] },
  { id: 'assets', label: '创作资源', icon: Layers, tabs: [{ id: 'meme-materials', label: '梗素材库', icon: Layers }] },
]

function Harness(props) {
  const [activeTab, setActiveTab] = useState('dashboard')
  return <div className="app-shell">
    <Sidebar tabGroups={groups} activeTab={activeTab} onTabChange={setActiveTab} theme="light" {...props} />
    <main><h1>{activeTab}</h1><button>页面操作</button></main>
  </div>
}

afterEach(() => { document.body.style.overflow = ''; vi.restoreAllMocks(); vi.unstubAllGlobals() })

it('exposes the brand before opening navigation and lets the brand return home', async () => {
  const user = userEvent.setup()
  render(<Harness />)
  const header = within(screen.getByRole('banner'))
  expect(header.getByText('GuichuHub')).toBeVisible()
  await user.click(within(screen.getByRole('navigation', { name: '快捷导航' })).getByRole('button', { name: '热梗' }))
  expect(screen.getByRole('heading', { name: 'memes' })).toBeVisible()
  await user.click(header.getByRole('button', { name: 'GuichuHub 首页' }))
  expect(screen.getByRole('heading', { name: 'dashboard' })).toBeVisible()
})

it('closes the drawer after choosing a destination and marks the selected page', async () => {
  const user = userEvent.setup()
  render(<Harness />)
  const menu = screen.getByRole('button', { name: '打开导航菜单' })
  await user.click(menu)
  const drawer = screen.getByRole('dialog', { name: '站点导航' })
  await user.click(within(drawer).getByRole('button', { name: '热梗', exact: true }))
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'memes' })).toBeVisible()
  expect(within(screen.getByRole('navigation', { name: '主导航' })).getByRole('button', { name: '热梗', exact: true })).toHaveAttribute('aria-current', 'page')
  expect(menu).toHaveFocus()
})

it('locks the background, traps focus, and restores focus and scrolling on Escape', async () => {
  const user = userEvent.setup()
  document.body.style.overflow = 'auto'
  render(<Harness />)
  const menu = screen.getByRole('button', { name: '打开导航菜单' })
  await user.click(menu)
  const drawer = screen.getByRole('dialog', { name: '站点导航' })
  const close = within(drawer).getByRole('button', { name: '关闭导航菜单' })
  expect(close).toHaveFocus()
  expect(document.body.style.overflow).toBe('hidden')
  expect(document.querySelector('.app-shell')).toHaveAttribute('inert')
  await user.tab({ shift: true })
  expect(within(drawer).getByRole('button', { name: 'B 站账号登录' })).toHaveFocus()
  await user.tab()
  expect(close).toHaveFocus()
  await user.keyboard('{Escape}')
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(document.querySelector('.app-shell')).not.toHaveAttribute('inert')
  expect(document.body.style.overflow).toBe('auto')
  expect(menu).toHaveFocus()
})

it('closes the drawer before opening login and supports dismissal using its backdrop', async () => {
  const user = userEvent.setup()
  const onOpenLogin = vi.fn()
  render(<Harness onOpenLogin={onOpenLogin} />)
  await user.click(screen.getByRole('button', { name: '打开导航菜单' }))
  await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'B 站账号登录' }))
  expect(onOpenLogin).toHaveBeenCalledOnce()
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: '打开导航菜单' }))
  await user.click(screen.getByRole('button', { name: '关闭导航遮罩', hidden: true }))
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
})

it('preserves guest and member restrictions for refresh and developer navigation', async () => {
  const user = userEvent.setup()
  const onDevBlocked = vi.fn()
  const devTab = { id: 'dev', label: '开发者后台' }
  const { rerender } = render(<Harness devTab={devTab} onDevBlocked={onDevBlocked} />)
  expect(screen.queryByRole('button', { name: '刷新数据' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: '开发者后台' })).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'B 站账号登录' })).toBeInTheDocument()
  rerender(<Harness devTab={devTab} onDevBlocked={onDevBlocked} biliUser={{ name: '测试用户' }} />)
  await user.click(screen.getByRole('button', { name: '开发者后台' }))
  expect(onDevBlocked).toHaveBeenCalledOnce()
  expect(screen.getByRole('heading', { name: 'dashboard' })).toBeVisible()
  expect(screen.queryByRole('button', { name: '刷新数据' })).not.toBeInTheDocument()
})

it('keeps administrator refresh, account logout, and developer navigation available', async () => {
  const user = userEvent.setup()
  const onRefresh = vi.fn(), onLogout = vi.fn()
  render(<Harness isAdmin biliUser={{ name: '站长' }} onRefresh={onRefresh} onLogout={onLogout}
    devTab={{ id: 'dev', label: '开发者后台' }} />)
  await user.click(screen.getByRole('button', { name: '刷新数据' }))
  expect(onRefresh).toHaveBeenCalledOnce()
  await user.click(screen.getByRole('button', { name: '开发者后台' }))
  expect(screen.getByRole('heading', { name: 'dev' })).toBeVisible()
  expect(screen.getByText('管理员')).toBeVisible()
  await user.click(screen.getByRole('button', { name: /站长/ }))
  await user.click(screen.getByRole('button', { name: '退出登录' }))
  expect(onLogout).toHaveBeenCalledOnce()
})

it('preserves the hidden administrator shortcut on the header brand', async () => {
  const user = userEvent.setup()
  const onAdminLogin = vi.fn()
  render(<Harness onAdminLogin={onAdminLogin} />)
  const brand = screen.getByRole('button', { name: 'GuichuHub 首页' })
  for (let i = 0; i < 4; i++) await user.click(brand)
  expect(onAdminLogin).not.toHaveBeenCalled()
  await user.click(brand)
  expect(onAdminLogin).toHaveBeenCalledOnce()
})

it('restores focus to the brand when resizing and the selected desktop group is hidden', async () => {
  const user = userEvent.setup()
  const desktop = { matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }
  vi.stubGlobal('matchMedia', () => desktop)
  render(<Harness />)
  const navigation = within(screen.getByRole('navigation', { name: '主导航' }))
  await user.click(navigation.getByRole('button', { name: '热梗', exact: true }))
  await user.click(navigation.getByRole('button', { name: '内容趋势' }))
  await user.click(screen.getByRole('button', { name: '打开导航菜单' }))
  desktop.matches = true
  const onResize = desktop.addEventListener.mock.calls[0][1]
  const { act } = await import('@testing-library/react')
  act(() => onResize(desktop))
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'GuichuHub 首页' })).toHaveFocus()
})

it('keeps every destination usable when the desktop island is collapsed', async () => {
  const user = userEvent.setup()
  render(<Harness />)
  const collapse = screen.getByRole('button', { name: '收起侧边栏' })
  expect(collapse).toHaveAttribute('aria-expanded', 'true')
  await user.click(collapse)
  expect(screen.getByRole('button', { name: '展开侧边栏' })).toHaveAttribute('aria-expanded', 'false')
  await user.click(within(screen.getByRole('navigation', { name: '主导航' })).getByRole('button', { name: '潜力视频', exact: true }))
  expect(screen.getByRole('heading', { name: 'videos' })).toBeVisible()
  await user.click(screen.getByRole('button', { name: '展开侧边栏' }))
  expect(screen.getByRole('button', { name: '收起侧边栏' })).toHaveAttribute('aria-expanded', 'true')
})

it('uses full navigation in the narrow-screen drawer even after collapsing the desktop island', async () => {
  const user = userEvent.setup()
  render(<Harness />)
  await user.click(screen.getByRole('button', { name: '收起侧边栏' }))
  await user.click(screen.getByRole('button', { name: '打开导航菜单' }))
  const drawer = within(screen.getByRole('dialog', { name: '站点导航' }))
  expect(drawer.getByRole('button', { name: '内容趋势' })).toHaveAttribute('aria-expanded', 'true')
  await user.click(drawer.getByRole('button', { name: '潜力视频' }))
  expect(screen.getByRole('heading', { name: 'videos' })).toBeVisible()
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: '展开侧边栏' })).toHaveAttribute('aria-expanded', 'false')
})
