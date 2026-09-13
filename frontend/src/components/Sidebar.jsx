import { useState, useMemo, useRef } from 'react'
import { RefreshCw, Star, User, LogOut, Menu, X, Clock, Sun, Moon, ChevronDown, PanelLeftClose, PanelLeftOpen, Code2, ShieldCheck } from 'lucide-react'

export default function Sidebar({
  tabGroups = [], devTab, activeTab, onTabChange,
  onRefresh, loading, crawling,
  lastUpdated, isLive, liveExpired,
  onToggleFavorites, favoritesCount,
  onOpenLogin, biliUser, onLogout,
  isAdmin, onAdminLogin, onDevBlocked,
  theme, onToggleTheme,
}) {
  const [showMenu, setShowMenu] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)
  // 侧边栏整体折叠（仅影响桌面悬浮岛宽度）
  const [collapsed, setCollapsed] = useState(false)
  // 父级组展开状态：默认全部展开（用户要求，不再只展开激活 tab 所在组）
  const initialExpanded = useMemo(() => {
    const m = {}
    tabGroups.forEach(g => { m[g.id] = true })
    return m
  }, [])
  const [expandedGroups, setExpandedGroups] = useState(initialExpanded)
  const toggleGroup = (gid) => setExpandedGroups(s => ({ ...s, [gid]: !s[gid] }))
  // 当激活 tab 改变时，如果新激活所属组是折叠的，自动展开它
  const ensureGroupOpen = (gid) => {
    if (!expandedGroups[gid]) setExpandedGroups(s => ({ ...s, [gid]: true }))
  }

  // 隐蔽超管入口：品牌 logo 连续点击 5 次（1.5s 窗口内）触发写口令登录弹窗
  const logoClicks = useRef(0)
  const logoClickTimer = useRef(null)
  const onLogoClick = () => {
    logoClicks.current += 1
    if (logoClickTimer.current) clearTimeout(logoClickTimer.current)
    logoClickTimer.current = setTimeout(() => { logoClicks.current = 0 }, 1500)
    if (logoClicks.current >= 5) {
      logoClicks.current = 0
      if (logoClickTimer.current) clearTimeout(logoClickTimer.current)
      if (onAdminLogin) onAdminLogin()
    }
  }

  // 内容主体：同时被桌面悬浮岛 / 移动端抽屉复用
  // collapsed 时隐藏文字，只保留图标；子菜单区域也收起（由外层 width 控制溢出隐藏）

  const BrandHeader = () => (
    <div className={`flex min-h-10 items-center ${collapsed ? 'justify-center px-0' : 'gap-3 px-1'}`}>
      <div className="relative shrink-0 w-10 h-10 rounded-2xl
                      bg-gradient-to-br from-bili-default via-neon-violet to-neon-cyan
                      shadow-glow-pink animate-glow-breath
                      flex items-center justify-center" onClick={onLogoClick}>
        <div className="flex items-end gap-[3px] h-[18px]">
          <span className="w-[3px] h-[55%] rounded-full bg-white/95" />
          <span className="w-[3px] h-[100%] rounded-full bg-white" />
          <span className="w-[3px] h-[75%] rounded-full bg-white/95" />
        </div>
      </div>
      {!collapsed && (
        <div className="w-[156px] shrink-0 overflow-hidden whitespace-nowrap">
          <h1 className="whitespace-nowrap text-[0.98rem] font-bold text-haze-50 leading-tight tracking-tight">
            鬼畜灵感看板
          </h1>
          <p className="mt-0.5 whitespace-nowrap text-[10.5px] tracking-[0.18em] text-haze-400">KICHOU · INSIGHT</p>
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
        <RefreshCw size={12} className="animate-spin shrink-0" />
        <span className="truncate">数据更新中…</span>
      </div>
    ) : (
      <div className="flex items-center gap-1.5 px-1 text-[11px] text-haze-400">
        <Clock size={12} className="shrink-0" />
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
          title={`${group.label} · ${shortcut.label}`}
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
          <Icon size={18} className={isActive ? 'text-bili-default' : 'text-haze-400 group-hover:text-haze-100'} />
        </button>
      )
    }
    // 单 tab 的组：父级直接做 tab 按钮，不做展开折叠
    if (onlyChild) {
      const isActive = activeTab === singleTab.id
      return (
        <button
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
          <group.icon size={17}
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
          onClick={() => toggleGroup(group.id)}
          className={
            'group relative w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-semibold transition-all duration-200 ' +
            (hasActiveChild
              ? 'text-haze-100 hover:bg-white/5'
              : 'text-haze-400 hover:text-haze-100 hover:bg-white/5')
          }>
          <group.icon size={16} className={
            'shrink-0 ' + (hasActiveChild ? 'text-bili-default' : 'text-haze-400 group-hover:text-haze-200')
          } />
          <span className="truncate text-[0.82rem] tracking-wide">{group.label}</span>
          <ChevronDown size={14}
            className={'ml-auto shrink-0 transition-transform duration-300 ease-out ' +
              (isOpen ? 'rotate-180 text-bili-default' : 'text-haze-500')} />
        </button>
        {/* 子菜单：缩进 + 高度/透明度动效 */}
        <div className={
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
                  <tab.icon size={15} className={
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
          onClick={handleClick}
          className={
            'w-full flex items-center justify-center py-2.5 rounded-xl transition-all duration-200 ' +
            (isActive
              ? 'bg-bili-default/10 text-bili-default shadow-[inset_0_0_0_1px_rgba(0,174,236,0.18)]'
              : 'text-haze-300 hover:bg-white/5 hover:text-haze-50')
          }>
          <Code2 size={18} />
        </button>
      )
    }
    const isActive = activeTab === devTab.id
    return (
      <button
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
        <Code2 size={17} className={isActive ? 'text-bili-default' : 'text-haze-400'} />
        <span className="truncate">{devTab.label}</span>
      </button>
    )
  }

  const ActionPanel = () => (
    <div className="space-y-2">
      {!collapsed ? (
        <>
          <button
            onClick={onToggleTheme}
            className="w-full flex items-center gap-2.5 px-3 py-2.5 rounded-xl font-medium text-[0.82rem]
                       bg-haze-50/5 hover:bg-haze-50/8 text-haze-50 border border-haze-50/10 transition-all"
            title={theme === 'dark' ? '切换到日间模式' : '切换到夜间模式'}>
            {theme === 'dark'
              ? <Sun size={15} className="shrink-0 text-haze-300" />
              : <Moon size={15} className="shrink-0 text-haze-300" />}
            <span className="truncate">{theme === 'dark' ? '切换到日间模式' : '切换到夜间模式'}</span>
          </button>
          <button
            onClick={onToggleFavorites}
            className="w-full flex items-center gap-2.5 px-3 py-2.5 rounded-xl font-medium text-[0.82rem]
                       text-bili-default bg-bili-default/6 hover:bg-bili-default/12
                       border border-bili-default/20 transition-all">
            <Star size={15} className="shrink-0 text-bili-default" />
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
              <RefreshCw size={15} className={`shrink-0 ${(loading || crawling) ? 'animate-spin' : ''}`} />
              <span className="truncate font-semibold tracking-wide">{crawling ? '更新中…' : loading ? '加载中…' : '刷新数据'}</span>
            </button>
          )}
        </>
      ) : (
        <>
          <button onClick={onToggleTheme} title={theme === 'dark' ? '切换到日间模式' : '切换到夜间模式'}
            className="kb-icon-btn w-full !h-10 !rounded-xl text-haze-300 hover:!text-haze-50">
            {theme === 'dark' ? <Sun size={17} /> : <Moon size={17} />}
          </button>
          <button onClick={onToggleFavorites} title="我的收藏"
            className="kb-icon-btn w-full !h-10 !rounded-xl text-bili-default hover:!bg-bili-default/10">
            <Star size={17} />
          </button>
          {isAdmin && (
            <button onClick={onRefresh} title="刷新数据" disabled={loading || crawling}
              className="w-full flex items-center justify-center h-10 rounded-xl
                         bg-bili-default text-white
                         shadow-[0_4px_14px_-4px_rgba(0,174,236,0.55)]
                         disabled:opacity-40 disabled:cursor-not-allowed">
              <RefreshCw size={16} className={(loading || crawling) ? 'animate-spin' : ''} />
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
              ) : <div className="w-full h-full flex items-center justify-center"><User size={14} className="text-haze-300" /></div>}
            </div>
            {isAdmin && (
              <span className="absolute -bottom-0.5 -right-0.5 w-3.5 h-3.5 rounded-full bg-bili-default
                               ring-2 ring-void-950 flex items-center justify-center" title="管理员">
                <ShieldCheck size={9} className="text-white" />
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
                ) : <User size={12} className="w-full h-full flex items-center justify-center text-haze-300" />}
              </div>
              <span className="truncate">{biliUser.name}</span>
              {isAdmin && (
                <span className="ml-auto shrink-0 inline-flex items-center gap-1 px-1.5 py-[2px] rounded-full
                                 text-[10px] font-semibold bg-bili-default/15 text-bili-default"
                      title="管理员账号">
                  <ShieldCheck size={10} />管理员
                </span>
              )}
            </button>
            {showMenu && (
              <>
                <div className="fixed inset-0 z-10" onClick={() => setShowMenu(false)} />
                <div className="kb-card absolute right-3 mt-2 w-44 py-1 z-20">
                  <div className="inner">
                    <button onClick={() => { onLogout(); setShowMenu(false) }}
                            className="w-full flex items-center gap-2 px-4 py-2 text-sm text-haze-300 hover:bg-haze-50/8 rounded-lg">
                      <LogOut size={15} /> 退出登录
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
            <User size={17} />
          </button>
        ) : (
          <button
            onClick={onOpenLogin}
            className="w-full flex items-center gap-2.5 px-3 py-2.5 rounded-xl font-medium text-[0.82rem]
                       bg-haze-50/5 hover:bg-haze-50/8 text-haze-50 border border-haze-50/10 transition-all">
            <User size={15} className="shrink-0 text-haze-300" />
            <span className="truncate">B 站账号登录</span>
          </button>
        )
      )}
    </div>
  )

  // ══════════════════════ 桌面端：悬浮岛 ══════════════════════
  // 由外层容器做 sticky + 上下外边距，形成"岛"的视觉
  // 圆形折叠 puck 悬浮在岛右边缘中部，BrandHeader 内不再有按钮
  const Desktop = (
    <aside className="hidden md:flex shrink-0 sticky top-0 h-screen z-40 pt-4 pb-4 pr-0 pl-4">
      <div className={
        'kb-island flex flex-col relative h-full shrink-0 transition-[width,max-width] duration-300 ease-[cubic-bezier(.2,.7,.2,1)] ' +
        (collapsed ? 'kb-island--collapsed' : 'kb-island--expanded')
      }>
        {/* 圆形折叠 puck：悬浮在岛右边缘中部，展开/折叠两态都贴边
            定位策略（用户第 3 次修正）：
              · 父 kb-island 带 relative → 本按钮使用 absolute right-0 贴岛内右边缘。
              · 不使用任何 transform translate 做居中/偏移（会进 GPU 合成层，与
                父 width transition 合并不一致 → 视觉错位/hover 抖动）。
              · 改为 margin-right: -16px 把一半 (32÷2) 推出岛外；
                改为 margin-top: -16px 做垂直居中。
              · 不声明任何 transition，hover 仅瞬时改色（保证"按钮不要移动"）。 */}
        <button
          onClick={() => setCollapsed(v => !v)}
          className="kb-collapse-puck absolute right-0 top-1/2 mr-[-16px] mt-[-16px]
                     z-50 w-8 h-8 rounded-full kb-card
                     flex items-center justify-center border border-white/10"
          title={collapsed ? '展开侧边栏' : '折叠侧边栏'}
          aria-label="切换侧边栏折叠"
        >
          {collapsed ? <PanelLeftOpen size={13} className="text-haze-50" /> : <PanelLeftClose size={13} className="text-haze-50" />}
        </button>
        <div className="overflow-hidden px-4 pt-5 pb-3">
          <BrandHeader />
        </div>

        <div className="px-4 pb-3">
          <StatusLine />
        </div>

        <nav className="flex-1 overflow-y-auto px-3 py-1 space-y-1 kb-scroll-slim">
          {tabGroups.map(g => <NavGroup key={g.id} group={g} />)}
          <div className="mt-2">
            <DevEntry />
          </div>
        </nav>

        <div className="border-t border-white/5 px-3.5 py-3 mt-auto">
          <ActionPanel />
        </div>
      </div>
    </aside>
  )

  // ══════════════════════ 移动端：抽屉（沿用旧行为，不做岛 + 折叠，屏幕太小没必要） ══════════════════════
  const Mobile = (
    <>
      <button
        onClick={() => setMobileOpen(true)}
        className="md:hidden fixed top-3 left-3 z-50 kb-icon-btn
                   bg-void-800/90 backdrop-blur border border-white/8 text-haze-100"
        aria-label="菜单">
        <Menu size={18} />
      </button>
      {mobileOpen && (
        <>
          <div className="md:hidden fixed inset-0 bg-black/50 backdrop-blur-[1px] z-40"
               onClick={() => setMobileOpen(false)} />
          <aside className="md:hidden fixed inset-y-0 left-0 w-[260px] bg-void-950 z-50
                            flex flex-col shadow-glow-pink animate-stagger-in overflow-hidden">
            <button onClick={() => setMobileOpen(false)}
                    className="absolute top-3 right-3 kb-icon-btn z-10"
                    aria-label="关闭">
              <X size={17} />
            </button>
            <div className="px-5 pt-6 pb-4">
              <BrandHeader />
            </div>
            <div className="px-5 pb-3">
              <StatusLine />
            </div>
            <nav className="flex-1 overflow-y-auto px-3.5 py-1 space-y-1">
              {tabGroups.map(g => <NavGroup key={g.id} group={g} />)}
              <div className="mt-2">
                <DevEntry />
              </div>
            </nav>
            <div className="border-t border-white/5 px-4 py-3.5">
              <ActionPanel />
            </div>
          </aside>
        </>
      )}
    </>
  )

  return <>{Desktop}{Mobile}</>
}
