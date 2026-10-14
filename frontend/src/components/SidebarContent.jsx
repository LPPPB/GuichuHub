import { useMemo, useState } from 'react'
import { RefreshCw, Star, User, LogOut, Clock, Sun, Moon, ChevronDown, Code2, ShieldCheck } from 'lucide-react'

// Original sidebar presentation from a7bd796, shared by the desktop island and mobile drawer.
export default function SidebarContent({
  tabGroups = [], devTab, activeTab, onTabChange, collapsed = false, drawer = false, label,
  onRefresh, loading, crawling, lastUpdated, isLive, liveExpired,
  onToggleFavorites, favoritesCount, onOpenLogin, biliUser, onLogout,
  isAdmin, onDevBlocked, theme, onToggleTheme, onLogoClick,
}) {
  const [showMenu, setShowMenu] = useState(false)
  const initialExpanded = useMemo(() => {
    const m = {}
    tabGroups.forEach(g => { m[g.id] = true })
    return m
  }, [])
  const [expandedGroups, setExpandedGroups] = useState(initialExpanded)
  const toggleGroup = (gid) => setExpandedGroups(s => ({ ...s, [gid]: !s[gid] }))

  const BrandHeader = () => (
    <div className={`flex min-h-10 items-center ${collapsed ? 'justify-center px-0' : 'gap-3 px-1'}`}>
      <button type="button" aria-label="品牌标志" className="relative shrink-0 w-10 h-10 rounded-2xl
                      bg-gradient-to-br from-bili-default via-neon-violet to-neon-cyan
                      shadow-glow-pink animate-glow-breath
                      flex items-center justify-center" onClick={onLogoClick}>
        <div className="flex items-end gap-[3px] h-[18px]">
          <span className="w-[3px] h-[55%] rounded-full bg-white/95" />
          <span className="w-[3px] h-[100%] rounded-full bg-white" />
          <span className="w-[3px] h-[75%] rounded-full bg-white/95" />
        </div>
      </button>
      {!collapsed && (
        <div className="w-[156px] shrink-0 overflow-hidden whitespace-nowrap">
          <p className="whitespace-nowrap text-[0.98rem] font-bold text-haze-50 leading-tight tracking-tight">
            GuichuHub
          </p>
          <p className="mt-0.5 whitespace-nowrap text-[10.5px] tracking-wide text-haze-300">个人技术小站 · 鬼畜看板</p>
          {isLive && (
            <span className={`inline-flex items-center gap-1 mt-1.5 px-2 py-[2px] rounded-full text-[10px] font-medium ${
              liveExpired ? 'kb-chip kb-chip--ghost' : 'kb-chip kb-chip--emerald'
            }`}>
              <span className={`w-1.5 h-1.5 rounded-full ${
                liveExpired ? 'bg-haze-500' : 'bg-neon-emerald animate-pulse-dot'
              }`} />
              {liveExpired ? '已过期' : 'LIVE'}
            </span>
          )}
        </div>
      )}
    </div>
  )

  const StatusLine = () => collapsed ? null : (
    crawling ? (
      <div className="flex items-center gap-2 text-xs font-medium rounded-xl
                      px-3 py-2 kb-chip--pink">
        <RefreshCw aria-hidden="true" size={12} className="animate-spin shrink-0" />
        <span className="truncate">数据更新中…</span>
      </div>
    ) : (
      <div className="flex items-center gap-1.5 px-1 text-[11px] text-haze-400">
        <Clock aria-hidden="true" size={12} className="shrink-0" />
        <span className="truncate">{lastUpdated ? `${lastUpdated}` : '加载中…'}</span>
      </div>
    )
  )

  const NavGroup = ({ group }) => {
    const isOpen = !!expandedGroups[group.id]
    const hasActiveChild = group.tabs.some(t => t.id === activeTab)
    const onlyChild = group.tabs.length === 1
    const singleTab = group.tabs[0]
    // 折叠态（collapsed）下：整组压缩为一个按钮——若单子则直接跳转单子，若多子则跳到第一个活跃或首个
    if (collapsed) {
      const shortcut = onlyChild ? singleTab : (group.tabs.find(t => t.id === activeTab) || group.tabs[0])
      const Icon = shortcut.icon
      const isActive = activeTab === shortcut.id
      return (
        <button
          title={`${group.label} · ${shortcut.label}`} aria-label={shortcut.label} aria-current={isActive ? "page" : undefined}
          onClick={() => { onTabChange(shortcut.id) }}
          className={
            'group relative w-full flex items-center justify-center py-2.5 rounded-xl transition-all duration-200 ' +
            (isActive
              ? 'bg-bili-default/10 text-bili-default shadow-[inset_0_0_0_1px_rgba(0,174,236,0.18)]'
              : 'text-haze-300 hover:bg-white/5 hover:text-haze-50')
          }>
          {isActive && (
            <span className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-5 rounded-r
                             bg-gradient-to-b from-bili-default to-bili-dark" />
          )}
          <Icon aria-hidden="true" size={18} className={isActive ? 'text-bili-default' : 'text-haze-400 group-hover:text-haze-100'} />
        </button>
      )
    }
    // 单 tab 的组：父级直接做 tab 按钮，不做展开折叠
    if (onlyChild) {
      const isActive = activeTab === singleTab.id
      return (
        <button
          aria-current={isActive ? "page" : undefined}
          onClick={() => onTabChange(singleTab.id)}
          className={
            'group relative w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-all duration-200 ' +
            (isActive
              ? 'bg-bili-default/10 text-bili-default shadow-[inset_0_0_0_1px_rgba(0,174,236,0.18)]'
              : 'text-haze-300 hover:bg-white/5 hover:text-haze-50')
          }>
          {isActive && (
            <span className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-5 rounded-r
                             bg-gradient-to-b from-bili-default to-bili-dark" />
          )}
          <group.icon aria-hidden="true" size={17}
            className={'shrink-0 transition-colors ' +
              (isActive ? 'text-bili-default' : 'text-haze-400 group-hover:text-haze-100')} />
          <span className="truncate">{group.label}</span>
        </button>
      )
    }
    // 多 tab 组：父级是可展开的归类标题；点击父级标题只展开/折叠，点击子级才切换 tab
    return (
      <div className="space-y-0.5">
        <button
          aria-expanded={isOpen} aria-controls={`${label}-${group.id}`}
          onClick={() => toggleGroup(group.id)}
          className={
            'group relative w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-semibold transition-all duration-200 ' +
            (hasActiveChild
              ? 'text-haze-100 hover:bg-white/5'
              : 'text-haze-400 hover:text-haze-100 hover:bg-white/5')
          }>
          <group.icon aria-hidden="true" size={16} className={
            'shrink-0 ' + (hasActiveChild ? 'text-bili-default' : 'text-haze-400 group-hover:text-haze-200')
          } />
          <span className="truncate text-[0.82rem] tracking-wide">{group.label}</span>
          <ChevronDown size={14}
            className={'ml-auto shrink-0 transition-transform duration-300 ease-out ' +
              (isOpen ? 'rotate-180 text-bili-default' : 'text-haze-500')} />
        </button>
        {/* 子菜单：缩进 + 高度/透明度动效 */}
        <div id={`${label}-${group.id}`} aria-hidden={!isOpen} inert={!isOpen ? '' : undefined} className={
          'overflow-hidden transition-[max-height,opacity,transform] duration-300 ease-[cubic-bezier(.2,.7,.2,1)] origin-top ' +
          (isOpen ? 'max-h-[360px] opacity-100 translate-y-0' : 'max-h-0 opacity-0 -translate-y-1')
        }>
          <div className="pt-1 pb-0.5 pl-3 pr-0 space-y-0.5 relative">
            {/* 缩进引导竖线 */}
            <span className="absolute left-[22px] top-0 bottom-1 w-px bg-gradient-to-b from-bili-default/30 via-bili-dark/20 to-transparent rounded-full pointer-events-none" />
            {group.tabs.map(tab => {
              const isActive = activeTab === tab.id
              return (
                <button
                  key={tab.id}
                  aria-current={isActive ? "page" : undefined}
                  onClick={() => { onTabChange(tab.id) }}
                  className={
                    'relative w-full flex items-center gap-2.5 pl-6 pr-3 py-2 rounded-[10px] text-[0.82rem] font-medium transition-all duration-200 ' +
                    (isActive
                      ? 'bg-bili-default/10 text-bili-default shadow-[inset_0_0_0_1px_rgba(0,174,236,0.18)]'
                      : 'text-haze-300 hover:bg-white/5 hover:text-haze-50')
                  }>
                  {isActive && (
                    <span className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-4 rounded-r
                                     bg-gradient-to-b from-bili-default to-bili-dark" />
                  )}
                  <tab.icon aria-hidden="true" size={15} className={
                    'shrink-0 ' +
                    (isActive ? 'text-bili-default' : 'text-haze-400 group-hover:text-haze-100')
                  } />
                  <span className="truncate">{tab.label}</span>
                </button>
              )
            })}
          </div>
        </div>
      </div>
    )
  }

  const DevEntry = () => {
    if (!devTab) return null
    // 未登录（无 B站账号）→ 隐藏开发者后台入口；登录后可见，普通用户点击提示无权限
    if (!biliUser) return null
    const handleClick = () => {
      if (!isAdmin) { if (onDevBlocked) onDevBlocked(); return }
      onTabChange(devTab.id)
    }
    if (collapsed) {
      const isActive = activeTab === devTab.id
      return (
        <button
          title={devTab.label}
          aria-label={devTab.label} aria-current={isActive ? "page" : undefined}
          onClick={handleClick}
          className={
            'w-full flex items-center justify-center py-2.5 rounded-xl transition-all duration-200 ' +
            (isActive
              ? 'bg-bili-default/10 text-bili-default shadow-[inset_0_0_0_1px_rgba(0,174,236,0.18)]'
              : 'text-haze-300 hover:bg-white/5 hover:text-haze-50')
          }>
          <Code2 aria-hidden="true" size={18} />
        </button>
      )
    }
    const isActive = activeTab === devTab.id
    return (
      <button
        aria-label={devTab.label} aria-current={isActive ? "page" : undefined}
          onClick={handleClick}
        className={
          'w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-all duration-200 ' +
          (isActive
            ? 'bg-bili-default/10 text-bili-default shadow-[inset_0_0_0_1px_rgba(0,174,236,0.18)]'
            : 'text-haze-300 hover:bg-white/5 hover:text-haze-50')
        }>
        {isActive && (
          <span className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-5 rounded-r
                           bg-gradient-to-b from-bili-default to-bili-dark" />
        )}
        <Code2 aria-hidden="true" size={17} className={isActive ? 'text-bili-default' : 'text-haze-400'} />
        <span className="truncate">{devTab.label}</span>
      </button>
    )
  }

  const ActionPanel = () => (
    <div className="space-y-2" data-sidebar-actions="">
      {!collapsed ? (
        <>
          <button
            onClick={onToggleTheme}
            className="w-full flex items-center gap-2.5 px-3 py-2.5 rounded-xl font-medium text-[0.82rem]
                       bg-haze-50/5 hover:bg-haze-50/8 text-haze-50 border border-haze-50/10 transition-all"
            title={theme === 'dark' ? '切换到日间模式' : '切换到夜间模式'}>
            {theme === 'dark'
              ? <Sun aria-hidden="true" size={15} className="shrink-0 text-haze-300" />
              : <Moon aria-hidden="true" size={15} className="shrink-0 text-haze-300" />}
            <span className="truncate">{theme === 'dark' ? '切换到日间模式' : '切换到夜间模式'}</span>
          </button>
          <button
            onClick={onToggleFavorites}
            className="w-full flex items-center gap-2.5 px-3 py-2.5 rounded-xl font-medium text-[0.82rem]
                       text-bili-default bg-bili-default/6 hover:bg-bili-default/12
                       border border-bili-default/20 transition-all">
            <Star aria-hidden="true" size={15} className="shrink-0 text-bili-default" />
            <span className="truncate">我的收藏</span>
            {favoritesCount > 0 && (
              <span className="ml-auto text-[11px] font-bold tabular-nums px-2 py-[2px] rounded-full
                               bg-bili-default text-white shrink-0">
                {favoritesCount}
              </span>
            )}
          </button>
          {isAdmin && (
            <button
              onClick={onRefresh}
              disabled={loading || crawling}
              className="w-full flex items-center gap-2.5 px-3 py-2.5 rounded-xl font-medium text-[0.82rem]
                         bg-bili-default hover:bg-bili-default/92 text-white
                         disabled:opacity-40 disabled:cursor-not-allowed
                         shadow-[0_4px_14px_-4px_rgba(0,174,236,0.55)] transition-all
                         relative overflow-hidden">
              <RefreshCw aria-hidden="true" size={15} className={`shrink-0 ${(loading || crawling) ? 'animate-spin' : ''}`} />
              <span className="truncate font-semibold tracking-wide">{crawling ? '更新中…' : loading ? '加载中…' : '刷新数据'}</span>
            </button>
          )}
        </>
      ) : (
        <>
          <button onClick={onToggleTheme} title={theme === 'dark' ? '切换到日间模式' : '切换到夜间模式'}
            className="kb-icon-btn w-full !h-10 !rounded-xl text-haze-300 hover:!text-haze-50">
            {theme === 'dark' ? <Sun aria-hidden="true" size={17} /> : <Moon aria-hidden="true" size={17} />}
          </button>
          <button onClick={onToggleFavorites} title="我的收藏"
            className="kb-icon-btn w-full !h-10 !rounded-xl text-bili-default hover:!bg-bili-default/10">
            <Star aria-hidden="true" size={17} />
          </button>
          {isAdmin && (
            <button onClick={onRefresh} title="刷新数据" disabled={loading || crawling}
              className="w-full flex items-center justify-center h-10 rounded-xl
                         bg-bili-default text-white
                         shadow-[0_4px_14px_-4px_rgba(0,174,236,0.55)]
                         disabled:opacity-40 disabled:cursor-not-allowed">
              <RefreshCw aria-hidden="true" size={16} className={(loading || crawling) ? 'animate-spin' : ''} />
            </button>
          )}
        </>
      )}

      {/* B站身份区块（全员开放）：访客可扫码登录自己的账号；
          登录后显示身份，管理员账号带徽标；凭证只落服务器会话表 */}
      {biliUser ? (
        collapsed ? (
          <div className="relative w-9 h-9 mx-auto" title={`${biliUser.name}${isAdmin ? '（管理员）' : ''}`}>
            <div className="w-9 h-9 rounded-full bg-gradient-to-br from-bili-default/40 to-neon-violet/40
                            overflow-hidden ring-2 ring-void-800">
              {biliUser.face ? (
                <img src={`/api/proxy/image?url=${encodeURIComponent(biliUser.face)}`}
                     alt={biliUser.name} className="w-full h-full object-cover" />
              ) : <div className="w-full h-full flex items-center justify-center"><User aria-hidden="true" size={14} className="text-haze-300" /></div>}
            </div>
            {isAdmin && (
              <span className="absolute -bottom-0.5 -right-0.5 w-3.5 h-3.5 rounded-full bg-bili-default
                               ring-2 ring-void-950 flex items-center justify-center" title="管理员">
                <ShieldCheck aria-hidden="true" size={9} className="text-white" />
              </span>
            )}
          </div>
        ) : (
          <div className="relative">
            <button
              onClick={() => setShowMenu(!showMenu)}
              className="w-full flex items-center gap-2.5 px-3 py-2.5 rounded-xl font-medium text-[0.82rem]
                         bg-haze-50/5 hover:bg-haze-50/8 text-haze-50 border border-haze-50/10 transition-all">
              <div className="w-6 h-6 rounded-full bg-gradient-to-br from-bili-default/40 to-neon-violet/40
                              overflow-hidden ring-2 ring-void-800 shrink-0">
                {biliUser.face ? (
                  <img src={`/api/proxy/image?url=${encodeURIComponent(biliUser.face)}`}
                       alt={biliUser.name} className="w-full h-full object-cover"
                       onError={(e) => { e.target.style.display = 'none' }} />
                ) : <User aria-hidden="true" size={12} className="w-full h-full flex items-center justify-center text-haze-300" />}
              </div>
              <span className="truncate">{biliUser.name}</span>
              {isAdmin && (
                <span className="ml-auto shrink-0 inline-flex items-center gap-1 px-1.5 py-[2px] rounded-full
                                 text-[10px] font-semibold bg-bili-default/15 text-bili-default"
                      title="管理员账号">
                  <ShieldCheck aria-hidden="true" size={10} />管理员
                </span>
              )}
            </button>
            {showMenu && (
              <>
                <div className="fixed inset-0 z-10" onClick={() => setShowMenu(false)} />
                <div className="kb-card absolute right-3 bottom-full mb-2 w-44 py-1 z-20">
                  <div className="inner">
                    <button onClick={() => { onLogout(); setShowMenu(false) }}
                            className="w-full flex items-center gap-2 px-4 py-2 text-sm text-haze-300 hover:bg-haze-50/8 rounded-lg">
                      <LogOut aria-hidden="true" size={15} /> 退出登录
                    </button>
                  </div>
                </div>
              </>
            )}
          </div>
        )
      ) : (
        collapsed ? (
          <button onClick={onOpenLogin} title="B 站账号登录"
            className="kb-icon-btn w-full !h-10 !rounded-xl">
            <User aria-hidden="true" size={17} />
          </button>
        ) : (
          <button
            onClick={onOpenLogin}
            className="w-full flex items-center gap-2.5 px-3 py-2.5 rounded-xl font-medium text-[0.82rem]
                       bg-haze-50/5 hover:bg-haze-50/8 text-haze-50 border border-haze-50/10 transition-all">
            <User aria-hidden="true" size={15} className="shrink-0 text-haze-300" />
            <span className="truncate">B 站账号登录</span>
          </button>
        )
      )}
    </div>
  )


  return <>
    <div className={drawer ? 'overflow-hidden px-5 pt-6 pb-4' : 'overflow-hidden px-4 pt-5 pb-3'}>{BrandHeader()}</div>
    <div className={drawer ? 'px-5 pb-3' : 'px-4 pb-3'}>{StatusLine()}</div>
    <nav id={drawer ? undefined : 'site-desktop-navigation'} aria-label={label}
      className={drawer ? 'flex-1 min-h-0 overflow-y-auto px-3.5 py-1 space-y-1' : 'flex-1 min-h-0 overflow-y-auto px-3 py-1 space-y-1 kb-scroll-slim'}>
      {tabGroups.map(group => <div key={group.id}>{NavGroup({group})}</div>)}
      <div className="mt-2">{DevEntry()}</div>
    </nav>
    <div className={drawer ? 'border-t border-white/5 px-4 py-3.5' : 'border-t border-white/5 px-3.5 py-3 mt-auto'}>{ActionPanel()}</div>
  </>
}
