import PublicLink from '../routing/PublicLink'
import { useState } from 'react'
import { ChevronRight, Clock, Code2, LogOut, Moon, RefreshCw, ShieldCheck, Star, Sun, User, X } from 'lucide-react'

export default function MobileDrawerContent({
  tabGroups = [], devTab, activeTab, onTabChange, onClose, onLogoClick, onBrandNavigate,
  theme, onToggleTheme, onToggleFavorites, favoritesCount,
  biliUser, isAdmin, onOpenLogin, onLogout, onDevBlocked,
  onRefresh, loading, crawling, lastUpdated,
}) {
  const [accountOpen, setAccountOpen] = useState(false)
  const themeLabel = theme === 'dark' ? '切换到日间模式' : '切换到夜间模式'
  return <>
    <div className="mobile-drawer-header">
      <PublicLink tabId="dashboard" onNavigate={onBrandNavigate || onTabChange} className="mobile-drawer-brand" aria-label="品牌标志" onClick={onLogoClick}>
        <img src="/favicon.svg" width="30" height="30" alt="" /><span>GuichuHub</span>
      </PublicLink>
      <button type="button" className="mobile-drawer-icon" aria-label={themeLabel} title={themeLabel} onClick={onToggleTheme}>
        {theme === 'dark' ? <Sun size={19} aria-hidden="true" /> : <Moon size={19} aria-hidden="true" />}
      </button>
      <button type="button" className="mobile-drawer-icon" aria-label="关闭导航菜单" onClick={onClose}><X size={20} aria-hidden="true" /></button>
    </div>
    <nav className="mobile-drawer-nav kb-scroll-slim" aria-label="抽屉导航">
      {tabGroups.map(group => {
        const home = group.tabs.some(tab => tab.id === 'dashboard')
        return <section key={group.id} className={home ? 'mobile-drawer-home' : 'mobile-drawer-group'}
          aria-label={group.label}>
          {!home && <h2>{group.label}</h2>}
          {group.tabs.map(tab => <PublicLink tabId={tab.id} onNavigate={onTabChange} className="mobile-drawer-item" key={tab.id}
            aria-current={activeTab === tab.id ? 'page' : undefined}>
            <tab.icon size={18} aria-hidden="true" /><span>{tab.label}</span>
          </PublicLink>)}
        </section>
      })}
      <div className="mobile-drawer-tools">
        <button type="button" className="mobile-drawer-item" aria-label="我的收藏" onClick={onToggleFavorites}>
          <Star size={18} aria-hidden="true" /><span>我的收藏</span>
          {favoritesCount > 0 && <span className="mobile-drawer-count" aria-hidden="true">{favoritesCount}</span>}
        </button>
        {devTab && biliUser && <button type="button" className="mobile-drawer-item"
          aria-current={activeTab === devTab.id ? 'page' : undefined}
          onClick={() => isAdmin ? onTabChange(devTab.id) : onDevBlocked?.()}>
          <Code2 size={18} aria-hidden="true" /><span>{devTab.label}</span>
        </button>}
        {isAdmin && <button type="button" className="mobile-drawer-item" aria-label="刷新数据"
          onClick={onRefresh} disabled={loading || crawling}>
          <RefreshCw size={18} aria-hidden="true" className={loading || crawling ? 'animate-spin' : ''} />
          <span>{crawling ? '更新中…' : loading ? '加载中…' : '刷新数据'}</span>
        </button>}
      </div>
    </nav>
    <div className="mobile-drawer-footer">
      {accountOpen && biliUser && <button type="button" className="mobile-drawer-item mobile-drawer-logout"
        onClick={() => { setAccountOpen(false); onLogout?.() }}>
        <LogOut size={18} aria-hidden="true" /><span>退出登录</span>
      </button>}
      <button type="button" className="mobile-drawer-account"
        aria-label={biliUser ? `${biliUser.name}${isAdmin ? ' 管理员' : ''}` : 'B 站账号登录'}
        aria-expanded={biliUser ? accountOpen : undefined}
        onClick={() => biliUser ? setAccountOpen(value => !value) : onOpenLogin?.()}>
        <span className="mobile-drawer-avatar">
          {biliUser?.face ? <img src={`/api/proxy/image?url=${encodeURIComponent(biliUser.face)}`} alt="" /> : <User size={20} aria-hidden="true" />}
        </span>
        <span className="mobile-drawer-identity">
          <strong>{biliUser ? biliUser.name : 'B 站账号登录'}</strong>
          <span>{biliUser ? isAdmin ? '管理员账号' : '已登录' : '登录后管理收藏'}</span>
        </span>
        {isAdmin ? <ShieldCheck size={17} aria-hidden="true" /> : <ChevronRight size={17} aria-hidden="true" />}
      </button>
      <div className="mobile-drawer-updated" aria-live="polite">
        {crawling ? <RefreshCw size={11} className="animate-spin" aria-hidden="true" /> : <Clock size={11} aria-hidden="true" />}
        <span>{crawling ? '数据更新中…' : lastUpdated ? `更新于 ${lastUpdated}` : '等待数据更新'}</span>
      </div>
    </div>
  </>
}
