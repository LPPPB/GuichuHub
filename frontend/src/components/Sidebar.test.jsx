import { useState } from 'react'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { Flame, Layers, TrendingUp, Trophy, Users, Zap } from 'lucide-react'
import Sidebar from './Sidebar'

const groups = [
  { id: 'home', label: '仪表盘', icon: TrendingUp, tabs: [{ id: 'dashboard', label: '总览', icon: TrendingUp }] },
  { id: 'trends', label: '内容趋势', icon: Flame, tabs: [
    { id: 'kichu-rank', label: '鬼畜榜', icon: Trophy },
    { id: 'memes', label: '热梗', icon: Flame },
    { id: 'videos', label: '潜力视频', icon: Zap },
  ] },
  { id: 'assets', label: '创作资源', icon: Layers, tabs: [{ id: 'meme-materials', label: '梗素材库', icon: Layers }] },
  { id: 'insight', label: '互动洞察', icon: Users, tabs: [{ id: 'up-trends', label: 'UP 主动态', icon: Users }] },
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
  await user.click(within(screen.getByRole('navigation', { name: '快捷导航' })).getByRole('link', { name: '潜力视频' }))
  expect(screen.getByRole('heading', { name: 'videos' })).toBeVisible()
  await user.click(header.getByRole('link', { name: 'GuichuHub 首页' }))
  expect(screen.getByRole('heading', { name: 'dashboard' })).toBeVisible()
})

it('closes the drawer after choosing a destination and marks the selected page', async () => {
  const user = userEvent.setup()
  render(<Harness />)
  const menu = screen.getByRole('button', { name: '打开导航菜单' })
  await user.click(menu)
  const drawer = screen.getByRole('dialog', { name: '站点导航' })
  await user.click(within(drawer).getByRole('link', { name: '热梗', exact: true }))
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'memes' })).toBeVisible()
  expect(within(screen.getByRole('navigation', { name: '主导航' })).getByRole('link', { name: '热梗', exact: true })).toHaveAttribute('aria-current', 'page')
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
  const brand = within(drawer).getByRole('link', { name: '品牌标志' })
  await user.click(brand)
  await user.tab({ shift: true })
  expect(within(drawer).getByRole('button', { name: 'B 站账号登录' })).toHaveFocus()
  await user.tab()
  expect(brand).toHaveFocus()
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
  const brand = screen.getByRole('link', { name: 'GuichuHub 首页' })
  for (let i = 0; i < 4; i++) await user.click(brand)
  expect(onAdminLogin).not.toHaveBeenCalled()
  await user.click(brand)
  expect(onAdminLogin).toHaveBeenCalledOnce()
  await user.click(within(screen.getByRole('navigation', { name: '主导航' })).getByRole('link', { name: '热梗', exact: true }))
  const sidebarBrand = within(screen.getByRole('complementary', { name: '桌面侧边栏' })).getByRole('link', { name: '品牌标志' })
  for (let i = 0; i < 5; i++) await user.click(sidebarBrand)
  expect(onAdminLogin).toHaveBeenCalledTimes(2)
  expect(screen.getByRole('heading', { name: 'dashboard' })).toBeVisible()
})

it('restores focus to the island brand when resizing and the selected desktop group is hidden', async () => {
  const user = userEvent.setup()
  const desktop = { matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }
  vi.stubGlobal('matchMedia', () => desktop)
  render(<Harness />)
  const navigation = within(screen.getByRole('navigation', { name: '主导航' }))
  await user.click(navigation.getByRole('link', { name: '热梗', exact: true }))
  await user.click(navigation.getByRole('button', { name: '内容趋势' }))
  await user.click(screen.getByRole('button', { name: '打开导航菜单' }))
  desktop.matches = true
  const onResize = desktop.addEventListener.mock.calls[0][1]
  const { act } = await import('@testing-library/react')
  act(() => onResize(desktop))
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(within(screen.getByRole('complementary', { name: '桌面侧边栏' })).getByRole('link', { name: '品牌标志' })).toHaveFocus()
})

it('keeps just the three requested shortcuts available after navigating', async () => {
  const user = userEvent.setup()
  render(<Harness />)
  const navigation = within(screen.getByRole('navigation', { name: '快捷导航' }))
  expect(navigation.getAllByRole('link').map(link => link.textContent.trim())).toEqual(['鬼畜榜', '潜力视频', 'UP 主动态'])
  await user.click(navigation.getByRole('link', { name: 'UP 主动态' }))
  expect(screen.getByRole('heading', { name: 'up-trends' })).toBeVisible()
  expect(navigation.getByRole('link', { name: 'UP 主动态' })).toHaveAttribute('aria-current', 'page')
  await user.click(navigation.getByRole('link', { name: '鬼畜榜' }))
  expect(screen.getByRole('heading', { name: 'kichu-rank' })).toBeVisible()
})

it('preserves the original compact group shortcuts and restores the full menu on expansion', async () => {
  const user = userEvent.setup()
  render(<Harness />)
  const collapse = screen.getByRole('button', { name: '收起侧边栏' })
  const navigation = within(screen.getByRole('navigation', { name: '主导航' }))
  await user.click(navigation.getByRole('link', { name: '潜力视频', exact: true }))
  expect(collapse).toHaveAttribute('aria-expanded', 'true')
  await user.click(collapse)
  expect(screen.getByRole('button', { name: '展开侧边栏' })).toHaveAttribute('aria-expanded', 'false')
  expect(navigation.queryByRole('link', { name: '热梗', exact: true })).not.toBeInTheDocument()
  await user.click(navigation.getByRole('link', { name: '潜力视频', exact: true }))
  expect(screen.getByRole('heading', { name: 'videos' })).toBeVisible()
  await user.click(screen.getByRole('button', { name: '展开侧边栏' }))
  expect(screen.getByRole('button', { name: '收起侧边栏' })).toHaveAttribute('aria-expanded', 'true')
  expect(navigation.getByRole('link', { name: '热梗', exact: true })).toBeVisible()
})

it('uses full navigation in the narrow-screen drawer even after collapsing the desktop island', async () => {
  const user = userEvent.setup()
  render(<Harness />)
  await user.click(screen.getByRole('button', { name: '收起侧边栏' }))
  await user.click(screen.getByRole('button', { name: '打开导航菜单' }))
  const drawer = within(screen.getByRole('dialog', { name: '站点导航' }))
  expect(drawer.getByRole('heading', { name: '内容趋势' })).toBeVisible()
  expect(drawer.queryByRole('button', { name: '内容趋势' })).not.toBeInTheDocument()
  await user.click(drawer.getByRole('link', { name: '潜力视频' }))
  expect(screen.getByRole('heading', { name: 'videos' })).toBeVisible()
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: '展开侧边栏' })).toHaveAttribute('aria-expanded', 'false')
})

it('presents flat drawer groups with working theme, favorites and account controls', async () => {
  const user = userEvent.setup()
  const onToggleTheme = vi.fn(), onToggleFavorites = vi.fn()
  render(<Harness onToggleTheme={onToggleTheme} onToggleFavorites={onToggleFavorites} />)
  await user.click(screen.getByRole('button', { name: '打开导航菜单' }))
  const drawer = within(screen.getByRole('dialog', { name: '站点导航' }))
  expect(drawer.getByRole('heading', { name: '内容趋势' })).toBeVisible()
  expect(drawer.getByRole('heading', { name: '创作资源' })).toBeVisible()
  expect(drawer.queryByText('个人技术小站 · 鬼畜看板')).not.toBeInTheDocument()
  await user.click(drawer.getByRole('button', { name: '切换到夜间模式' }))
  expect(onToggleTheme).toHaveBeenCalledOnce()
  expect(screen.getByRole('dialog')).toBeInTheDocument()
  await user.click(drawer.getByRole('button', { name: '我的收藏' }))
  expect(onToggleFavorites).toHaveBeenCalledOnce()
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
})
