import PublicLink from '../routing/PublicLink'
import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Menu, PanelLeftClose, PanelLeftOpen } from 'lucide-react'
import SidebarContent from './SidebarContent'
import MobileDrawerContent from './MobileDrawerContent'
import './Sidebar.css'

const shortcuts = ['kichu-rank', 'videos', 'up-trends']

export default function Sidebar(props) {
  const { tabGroups = [], activeTab, onTabChange, isLive, liveExpired, onAdminLogin } = props
  const [mobileOpen, setMobileOpen] = useState(false)
  const [collapsed, setCollapsed] = useState(false)
  const headerRef = useRef(null)
  const menuRef = useRef(null)
  const drawerRef = useRef(null)
  const clicks = useRef(0)
  const clickTimer = useRef(null)
  const quickTabs = shortcuts.map(id => tabGroups.flatMap(group => group.tabs).find(tab => tab.id === id)).filter(Boolean)

  useEffect(() => () => clearTimeout(clickTimer.current), [])

  useEffect(() => {
    if (!mobileOpen) return
    const drawer = drawerRef.current
    const frame = headerRef.current.closest('.app-shell')
    const wasInert = frame?.hasAttribute('inert')
    const previousOverflow = document.body.style.overflow
    frame?.setAttribute('inert', '')
    document.body.style.overflow = 'hidden'
    const initialFocus = drawer.querySelector('[aria-label="关闭导航菜单"]')
    initialFocus?.focus()
    const focusable = () => [...drawer.querySelectorAll('button:not(:disabled), a[href], [tabindex="0"]')]
      .filter(element => !element.closest('[hidden], [aria-hidden="true"], [inert]'))
    const onKeyDown = event => {
      if (event.key === 'Escape') { event.preventDefault(); setMobileOpen(false) }
      if (event.key !== 'Tab') return
      const elements = focusable()
      const first = elements[0], last = elements.at(-1)
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
    }
    const keepFocus = event => {
      if (!drawer.contains(event.target)) initialFocus?.focus()
    }
    const desktop = window.matchMedia?.('(min-width: 1024px)')
    const onResize = event => { if (event.matches) setMobileOpen(false) }
    desktop?.addEventListener('change', onResize)
    document.addEventListener('keydown', onKeyDown)
    document.addEventListener('focusin', keepFocus)
    return () => {
      desktop?.removeEventListener('change', onResize)
      document.removeEventListener('keydown', onKeyDown)
      document.removeEventListener('focusin', keepFocus)
      if (!wasInert) frame?.removeAttribute('inert')
      document.body.style.overflow = previousOverflow
      if (desktop?.matches) {
        const current = frame?.querySelector('.site-sidebar [aria-current="page"]')
        const target = current && !current.closest('[hidden], [aria-hidden="true"], [inert]') ? current : frame?.querySelector('.site-sidebar [aria-label="品牌标志"]')
        target?.focus()
      } else menuRef.current?.focus()
    }
  }, [mobileOpen])

  const navigate = id => { setMobileOpen(false); onTabChange(id) }
  const openPanel = callback => () => { setMobileOpen(false); callback?.() }
  const actions = { ...props, onOpenLogin: openPanel(props.onOpenLogin), onToggleFavorites: openPanel(props.onToggleFavorites) }
  const registerBrandClick = () => {
    clicks.current += 1
    clearTimeout(clickTimer.current)
    clickTimer.current = setTimeout(() => { clicks.current = 0 }, 1500)
    if (clicks.current >= 5) { clicks.current = 0; onAdminLogin?.() }
  }
  return <>
    <header className="site-header" ref={headerRef}>
      <div className="site-brandbar">
        <PublicLink tabId="dashboard" onNavigate={navigate} className="site-brand" aria-label="GuichuHub 首页" onClick={registerBrandClick}>
          <img src="/favicon.svg" width="36" height="36" alt="" />
          <span className="site-brand__name">GuichuHub</span>
        </PublicLink>
        <p className="site-brand__description">发现鬼畜热点，追踪创作趋势。</p>
        {isLive && <span className={`site-live ${liveExpired ? 'is-expired' : ''}`}><i />{liveExpired ? '数据已过期' : 'LIVE'}</span>}
        <button type="button" className="site-menu-button" ref={menuRef} onClick={() => setMobileOpen(true)}
          aria-label="打开导航菜单" aria-expanded={mobileOpen} aria-controls="site-navigation-drawer" aria-haspopup="dialog">
          <Menu size={19} aria-hidden="true" /><span>菜单</span>
        </button>
      </div>
      <nav className="site-shortcuts" aria-label="快捷导航">
        {quickTabs.map(tab => <PublicLink tabId={tab.id} onNavigate={navigate} key={tab.id} aria-current={activeTab === tab.id ? 'page' : undefined}>
          <tab.icon size={15} aria-hidden="true" /><span>{tab.label}</span>
        </PublicLink>)}
      </nav>
    </header>
    <aside className={`site-sidebar${collapsed ? ' site-sidebar--collapsed' : ''}`} aria-label="桌面侧边栏">
      <button type="button" className="site-sidebar__collapse" onClick={() => setCollapsed(value => !value)}
        aria-label={collapsed ? '展开侧边栏' : '收起侧边栏'} title={collapsed ? '展开侧边栏' : '收起侧边栏'}
        aria-expanded={!collapsed} aria-controls="site-desktop-navigation">
        {collapsed ? <PanelLeftOpen size={17} aria-hidden="true" /> : <PanelLeftClose size={17} aria-hidden="true" />}
      </button>
      <SidebarContent {...actions} tabGroups={tabGroups} collapsed={collapsed} label="主导航" onTabChange={navigate} onLogoClick={registerBrandClick} />
    </aside>
    {mobileOpen && createPortal(<div className="site-drawer-layer">
      <button type="button" className="site-drawer-backdrop" tabIndex={-1} aria-label="关闭导航遮罩" onClick={() => setMobileOpen(false)} />
      <div className="site-drawer" id="site-navigation-drawer" ref={drawerRef} role="dialog" aria-modal="true" aria-label="站点导航">
        <MobileDrawerContent {...actions} tabGroups={tabGroups} onTabChange={navigate} onBrandNavigate={onTabChange} onLogoClick={registerBrandClick} onClose={() => setMobileOpen(false)} />
      </div>
    </div>, document.body)}
  </>
}
