import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { ChevronDown, Clock, Code2, LogOut, Menu, Moon, PanelLeftClose, PanelLeftOpen, RefreshCw, ShieldCheck, Star, Sun, User, X } from 'lucide-react'
import './Sidebar.css'

const shortcuts = ['kichu-rank', 'memes', 'videos', 'meme-materials']

function Navigation({ tabGroups, devTab, activeTab, onNavigate, biliUser, isAdmin, onDevBlocked, label, collapsed = false }) {
  const [closedGroups, setClosedGroups] = useState({})
  return <nav className="site-navigation kb-scroll-slim" aria-label={label}>
    {tabGroups.map(group => {
      const Icon = group.icon
      const single = group.tabs.length === 1
      const open = !closedGroups[group.id]
      return <div className="site-nav-group" key={group.id}>
        {single ? <button type="button" className="site-nav-link" aria-label={group.label} title={collapsed ? group.label : undefined}
          aria-current={activeTab === group.tabs[0].id ? 'page' : undefined}
          onClick={() => onNavigate(group.tabs[0].id)}><Icon size={18} aria-hidden="true" /><span>{group.label}</span></button> : <>
          <button type="button" className="site-nav-group__title" aria-expanded={open}
            aria-controls={`${label}-${group.id}`}
            onClick={() => setClosedGroups(previous => ({ ...previous, [group.id]: open }))}>
            <Icon size={16} aria-hidden="true" /><span>{group.label}</span>
            <ChevronDown size={14} aria-hidden="true" className={open ? 'is-open' : ''} />
          </button>
          <div id={`${label}-${group.id}`} hidden={!open && !collapsed} className="site-nav-children">
            {group.tabs.map(tab => <button type="button" className="site-nav-link" key={tab.id}
              aria-label={tab.label} title={collapsed ? tab.label : undefined}
              aria-current={activeTab === tab.id ? 'page' : undefined} onClick={() => onNavigate(tab.id)}>
              <tab.icon size={16} aria-hidden="true" /><span>{tab.label}</span>
            </button>)}
          </div>
        </>}
      </div>
    })}
    {devTab && biliUser && <button type="button" className="site-nav-link"
      aria-label={devTab.label} title={collapsed ? devTab.label : undefined}
      aria-current={activeTab === devTab.id ? 'page' : undefined}
      onClick={() => isAdmin ? onNavigate(devTab.id) : onDevBlocked?.()}>
      <Code2 size={17} aria-hidden="true" /><span>{devTab.label}</span>
    </button>}
  </nav>
}

function Actions({ theme, onToggleTheme, onToggleFavorites, favoritesCount, isAdmin, loading, crawling,
  onRefresh, biliUser, onLogout, onOpenLogin }) {
  const [showAccount, setShowAccount] = useState(false)
  return <div className="site-nav-actions">
    <div className="site-nav-tools">
      <button type="button" className="site-nav-link" onClick={onToggleTheme}
        aria-label={theme === 'dark' ? '切换到日间模式' : '切换到夜间模式'} title={theme === 'dark' ? '切换到日间模式' : '切换到夜间模式'}>
        {theme === 'dark' ? <Sun size={17} aria-hidden="true" /> : <Moon size={17} aria-hidden="true" />}
        <span>{theme === 'dark' ? '切换到日间模式' : '切换到夜间模式'}</span>
      </button>
      <button type="button" className="site-nav-link" onClick={onToggleFavorites} aria-label="我的收藏" title="我的收藏">
        <Star size={17} aria-hidden="true" /><span>我的收藏</span>
        {favoritesCount > 0 && <span className="site-nav-count">{favoritesCount}</span>}
      </button>
      {isAdmin && <button type="button" className="site-nav-link" onClick={onRefresh} disabled={loading || crawling} aria-label="刷新数据" title="刷新数据">
        <RefreshCw size={17} aria-hidden="true" className={loading || crawling ? 'animate-spin' : ''} />
        <span>{crawling ? '更新中…' : loading ? '加载中…' : '刷新数据'}</span>
      </button>}
    </div>
    {biliUser ? <div className="site-account">
      <button type="button" className="site-nav-link" aria-label={`${biliUser.name}${isAdmin ? ' 管理员' : ''}`}
        title={`${biliUser.name}${isAdmin ? '（管理员）' : ''}`} aria-expanded={showAccount} onClick={() => setShowAccount(value => !value)}>
        {biliUser.face ? <img className="site-account__avatar" src={`/api/proxy/image?url=${encodeURIComponent(biliUser.face)}`} alt="" /> : <User size={17} aria-hidden="true" />}
        <span className="site-account__name">{biliUser.name}</span>
        {isAdmin && <span className="site-account__badge"><ShieldCheck size={13} aria-hidden="true" />管理员</span>}
        <ChevronDown size={14} aria-hidden="true" className="site-account__chevron" />
      </button>
      {showAccount && <button type="button" className="site-nav-link" aria-label="退出登录" title="退出登录" onClick={() => { setShowAccount(false); onLogout?.() }}>
        <LogOut size={16} aria-hidden="true" /><span>退出登录</span>
      </button>}
    </div> : <button type="button" className="site-nav-link" onClick={onOpenLogin} aria-label="B 站账号登录" title="B 站账号登录">
      <User size={17} aria-hidden="true" /><span>B 站账号登录</span>
    </button>}
  </div>
}

export default function Sidebar(props) {
  const { tabGroups = [], activeTab, onTabChange, lastUpdated, crawling, isLive, liveExpired, onAdminLogin } = props
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
    drawer.querySelector('button')?.focus()
    const focusable = () => [...drawer.querySelectorAll('button:not(:disabled), a[href], [tabindex="0"]')]
      .filter(element => !element.closest('[hidden]'))
    const onKeyDown = event => {
      if (event.key === 'Escape') { event.preventDefault(); setMobileOpen(false) }
      if (event.key !== 'Tab') return
      const elements = focusable()
      const first = elements[0], last = elements.at(-1)
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
    }
    const keepFocus = event => {
      if (!drawer.contains(event.target)) drawer.querySelector('button')?.focus()
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
        const target = current && !current.closest('[hidden]') ? current : headerRef.current?.querySelector('.site-brand')
        target?.focus()
      } else menuRef.current?.focus()
    }
  }, [mobileOpen])

  const navigate = id => { setMobileOpen(false); onTabChange(id) }
  const openPanel = callback => () => { setMobileOpen(false); callback?.() }
  const actions = { ...props, onOpenLogin: openPanel(props.onOpenLogin), onToggleFavorites: openPanel(props.onToggleFavorites) }
  const brandClick = () => {
    navigate('dashboard')
    clicks.current += 1
    clearTimeout(clickTimer.current)
    clickTimer.current = setTimeout(() => { clicks.current = 0 }, 1500)
    if (clicks.current >= 5) { clicks.current = 0; onAdminLogin?.() }
  }
  const status = <div className="site-nav-status">
    {crawling ? <RefreshCw size={13} className="animate-spin" aria-hidden="true" /> : <Clock size={13} aria-hidden="true" />}
    <span>{crawling ? '数据更新中…' : lastUpdated || '等待数据更新'}</span>
  </div>

  return <>
    <header className="site-header" ref={headerRef}>
      <div className="site-brandbar">
        <button type="button" className="site-brand" aria-label="GuichuHub 首页" onClick={brandClick}>
          <img src="/favicon.svg" width="36" height="36" alt="" />
          <span className="site-brand__name">GuichuHub</span>
        </button>
        <p className="site-brand__description">发现鬼畜热点，追踪创作趋势。</p>
        {isLive && <span className={`site-live ${liveExpired ? 'is-expired' : ''}`}><i />{liveExpired ? '数据已过期' : 'LIVE'}</span>}
        <button type="button" className="site-menu-button" ref={menuRef} onClick={() => setMobileOpen(true)}
          aria-label="打开导航菜单" aria-expanded={mobileOpen} aria-controls="site-navigation-drawer" aria-haspopup="dialog">
          <Menu size={19} aria-hidden="true" /><span>菜单</span>
        </button>
      </div>
      {activeTab === 'dashboard' && <nav className="site-shortcuts" aria-label="快捷导航">
        {quickTabs.map(tab => <button type="button" key={tab.id} onClick={() => navigate(tab.id)}>
          <tab.icon size={15} aria-hidden="true" /><span>{tab.label}</span>
        </button>)}
      </nav>}
    </header>
    <aside className={`site-sidebar${collapsed ? ' site-sidebar--collapsed' : ''}`} aria-label="桌面侧边栏">
      <button type="button" className="site-sidebar__collapse" onClick={() => setCollapsed(value => !value)}
        aria-label={collapsed ? '展开侧边栏' : '收起侧边栏'} title={collapsed ? '展开侧边栏' : '收起侧边栏'}
        aria-expanded={!collapsed} aria-controls="site-desktop-navigation">
        {collapsed ? <PanelLeftOpen size={17} aria-hidden="true" /> : <PanelLeftClose size={17} aria-hidden="true" />}
      </button>
      <div className="site-sidebar__intro">
        <div className="site-island-brand"><img src="/favicon.svg" width="36" height="36" alt="" />
          <div><p>GuichuHub</p><span>个人技术小站 · 鬼畜看板</span></div>
        </div>
        {status}
      </div>
      <div id="site-desktop-navigation" className="site-sidebar__navigation">
        <Navigation {...props} tabGroups={tabGroups} onNavigate={navigate} label="主导航" collapsed={collapsed} />
      </div>
      <Actions {...actions} />
    </aside>
    {mobileOpen && createPortal(<div className="site-drawer-layer">
      <button type="button" className="site-drawer-backdrop" tabIndex={-1} aria-label="关闭导航遮罩" onClick={() => setMobileOpen(false)} />
      <div className="site-drawer" id="site-navigation-drawer" ref={drawerRef} role="dialog" aria-modal="true" aria-label="站点导航">
        <div className="site-drawer__header">
          <span className="site-drawer__brand"><img src="/favicon.svg" width="32" height="32" alt="" />GuichuHub</span>
          <button type="button" className="site-drawer__close" aria-label="关闭导航菜单" onClick={() => setMobileOpen(false)}><X size={20} /></button>
        </div>
        {status}
        <Navigation {...props} tabGroups={tabGroups} onNavigate={navigate} label="抽屉导航" />
        <Actions {...actions} />
      </div>
    </div>, document.body)}
  </>
}
