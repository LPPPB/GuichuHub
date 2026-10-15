import { useState, useEffect, useRef, lazy, Suspense } from 'react'
import { api, verifyAdminSilent } from './utils/api'
import Sidebar from './components/Sidebar'
import MemeCard from './components/MemeCard'
import SongCard from './components/SongCard'
import VideoCard from './components/VideoCard'
import DanmakuCloud from './components/DanmakuCloud'
import CommentList from './components/CommentList'
import FavoritesPanel from './components/FavoritesPanel'
import MiniPlayer from './components/MiniPlayer'
import BilibiliLogin from './components/BilibiliLogin'
import OnlineBreakerChart from './components/OnlineBreakerChart'
import SiteFooter from './components/SiteFooter'
import { Flame, Music, Video, MessageCircle, Star, TrendingUp, Trophy, Zap, Sparkles, Users, Search, Tag, Code2, LayoutDashboard, LineChart, Layers, ScanSearch, ChevronRight, AlertTriangle } from 'lucide-react'

const UpTrends = lazy(() => import('./components/UpTrends'))
const BurstingVideos = lazy(() => import('./components/BurstingVideos'))
const DevConsole = lazy(() => import('./components/DevConsole'))

const LazyFallback = () => (
  <div className="flex items-center justify-center py-16">
    <div className="w-6 h-6 border-2 border-primary-500 border-t-transparent rounded-full animate-spin" />
  </div>
)

const EMPTY_DATA = {
  kichu_rank: [], hot_memes: [], hot_songs: [], hot_videos: [],
  material_candidates: [], meme_materials: [], danmaku_words: [],
  comments_gold: [], last_updated: null,
}

export default function App() {
  const [activeTab, setActiveTab] = useState('dashboard')
  const [data, setData] = useState(EMPTY_DATA)
  const [interactionQuality, setInteractionQuality] = useState([])
  const [tagHeat, setTagHeat] = useState([])
  const [risingWords, setRisingWords] = useState([])
  const [risingMeta, setRisingMeta] = useState(null)
  const maxHeat = Math.max(...(data.hot_memes || []).map((m) => Number(m.heat) || 0), 1)
  const [loading, setLoading] = useState(true)
  const [favorites, setFavorites] = useState([])
  const [showFavorites, setShowFavorites] = useState(false)
  const [showLogin, setShowLogin] = useState(false)
  // 顶部轻提示（如「需要管理员权限」）；3 秒自动消失
  const [notice, setNotice] = useState('')
  const noticeTimerRef = useRef(null)
  // 当前B站身份（扫码登录的账号；由 /auth/me 三态判定返回，访客未登录 = null）
  const [biliUser, setBiliUser] = useState(null)
  // 管理员身份（三态：写口令超管 / B站账号在管理员名单 / 访客）；访客 = false
  const [isAdmin, setIsAdmin] = useState(false)
  const [crawling, setCrawling] = useState(false)
  const crawlingRef = useRef(false)
  const [breakerTrend, setBreakerTrend] = useState([])
  const [breakerThreshold, setBreakerThreshold] = useState(3)
  const [isLive, setIsLive] = useState(false)
  const [liveExpired, setLiveExpired] = useState(false)
  const liveExpiryTimer = useRef(null)
  const [theme, setTheme] = useState(() => {
    if (typeof window === 'undefined') return 'dark'
    const saved = localStorage.getItem('kb-theme')
    if (saved === 'light' || saved === 'dark') return saved
    return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark'
  })

  const favKeyOf = (type, item) => {
    if (type === 'video') return `video:${item.bvid}`
    if (type === 'song')  return `song:${item.bvid}`
    if (type === 'meme')  return `meme:${item.keyword}`
    if (type === 'meme_material') return `meme_material:${item.name}`
    return `${type}:${item.id || JSON.stringify(item)}`
  }
  const favSet = new Set(favorites.map(f => favKeyOf(f.type, f.data || f)))
  const isFav = (t, it) => favSet.has(favKeyOf(t, it))

  useEffect(() => {
    loadData()
    loadFavorites() // 收藏归属由请求头自动区分（访客 UUID / 管理员）
    ;(async () => {
      // 超管口令静默校验（失效凭证自动清除）→ 三态身份判定（B站管理员会话在此生效）
      await verifyAdminSilent()
      await refreshIdentity()
    })()
  }, [])

  useEffect(() => {
    const root = document.documentElement
    if (theme === 'dark') root.classList.add('dark')
    else root.classList.remove('dark')
    localStorage.setItem('kb-theme', theme)
  }, [theme])
  const toggleTheme = () => setTheme(t => t === 'dark' ? 'light' : 'dark')

  useEffect(() => {
    let timer; let stopped = false; let inFlight = false
    const delay = () => (crawlingRef.current ? 3000 : 15000)
    const poll = async () => {
      if (document.hidden || inFlight || stopped) return
      inFlight = true
      try {
        const res = await api.getStatus()
        if (stopped) return
        if (res.success && res.data) {
          const isCrawling = !!res.data.crawling
          if (crawlingRef.current && !isCrawling) loadData()
          crawlingRef.current = isCrawling
          setCrawling(isCrawling)
          if (res.data.online_breaker?.trend)     setBreakerTrend(res.data.online_breaker.trend)
          if (res.data.online_breaker?.threshold != null) setBreakerThreshold(res.data.online_breaker.threshold)
        }
      } finally { inFlight = false }
      if (!stopped && !document.hidden) timer = setTimeout(poll, delay())
    }
    const onVisibility = () => {
      if (document.hidden) clearTimeout(timer)
      else { clearTimeout(timer); poll() }
    }
    document.addEventListener('visibilitychange', onVisibility)
    poll()
    return () => { stopped = true; clearTimeout(timer); document.removeEventListener('visibilitychange', onVisibility) }
  }, [])

  useEffect(() => {
    let cancelled = false
    api.getInteractionQuality(20).then(res => { if (!cancelled && res.success) setInteractionQuality(res.data || []) }).catch(() => {})
    return () => { cancelled = true }
  }, [data.last_updated, isLive])

  useEffect(() => {
    let cancelled = false
    api.getTagHeat(40).then(res => { if (!cancelled && res.success) setTagHeat(res.data || []) }).catch(() => {})
    api.getRisingWords(2, 6, 30).then(res => {
      if (!cancelled && res.success) {
        setRisingWords(res.data || [])
        setRisingMeta(res.meta || null)
      }
    }).catch(() => {})
    return () => { cancelled = true }
  }, [data.last_updated, isLive])

  useEffect(() => {
    return () => {
      if (liveExpiryTimer.current) { clearTimeout(liveExpiryTimer.current); liveExpiryTimer.current = null }
      if (noticeTimerRef.current) { clearTimeout(noticeTimerRef.current); noticeTimerRef.current = null }
    }
  }, [])

  const loadData = async () => {
    setLoading(true)
    const res = await api.getDashboard()
    if (res.success && res.data) {
      setData(res.data)
      const newIsLive = res.data.is_live || false
      setIsLive(newIsLive); setLiveExpired(false)
      if (liveExpiryTimer.current) { clearTimeout(liveExpiryTimer.current); liveExpiryTimer.current = null }
      if (newIsLive) {
        liveExpiryTimer.current = setTimeout(() => { setLiveExpired(true); liveExpiryTimer.current = null }, 10 * 60 * 1000)
      }
    }
    setLoading(false)
  }
  const loadFavorites = async () => { const res = await api.getFavorites(); if (res.success) setFavorites(res.data || []) }
  // 三态身份刷新：GET /auth/me → {admin, via, user}（口令超管 / B站管理员会话 / 访客）
  const refreshIdentity = async () => {
    const res = await api.getAuthMe()
    if (res.success && res.data) {
      setIsAdmin(!!res.data.admin)
      setBiliUser(res.data.user || null)
    }
  }
  // 身份登录成功（会话已写入 HttpOnly Cookie）：刷新身份与收藏归属后进入UP主动态
  const handleLoginSuccess = async () => { await refreshIdentity(); await loadFavorites(); setActiveTab('up-trends') }
  // 退出B站身份（api.logout 清除服务器会话与 HttpOnly Cookie）；口令超管身份不受影响，重判即可
  const handleLogout = async () => { await api.logout(); await refreshIdentity(); setActiveTab('dashboard') }
  const handleRefresh = async () => { const res = await api.refresh(); if (res.success || res.crawling) { crawlingRef.current = true; setCrawling(true) } }
  // 超管口令登录（应急后门）：成功后刷新身份（via=write_token）与（admin 归属的）收藏
  const handleAdminLogin = async () => {
    const res = await api.adminLogin()
    if (res && res.success) {
      await refreshIdentity()
      await loadFavorites()
    }
  }
  // 收藏需登录 B站账号（归属 mid，跨设备持久）；未登录触发统一登录弹窗
  const requireLogin = () => { if (!biliUser) { setShowLogin(true); return true } return false }
  const handleAddFavorite = async (type, item) => { if (requireLogin()) return; await api.addFavorite(type, item); await loadFavorites() }
  const handleRemoveFavorite = async (id) => { if (requireLogin()) return; await api.removeFavorite(id); await loadFavorites() }
  // 顶部轻提示：3 秒自动消失（无权限/操作反馈）
  const flashNotice = (msg) => {
    setNotice(msg)
    if (noticeTimerRef.current) clearTimeout(noticeTimerRef.current)
    noticeTimerRef.current = setTimeout(() => setNotice(''), 3000)
  }

  const trendColor = (label) => {
    switch (label) {
      case '爆发期': return 'kb-chip kb-chip--rose'
      case '上升期': return 'kb-chip kb-chip--pink'
      case '平稳期': return 'kb-chip kb-chip--ghost'
      case '衰退期': return 'kb-chip kb-chip--cyan'
      default: return 'kb-chip kb-chip--ghost'
    }
  }

  const formatNumber = (num) => {
    if (!num) return '0'
    if (num >= 100000000) return (num / 100000000).toFixed(1) + '亿'
    if (num >= 10000)     return (num / 10000).toFixed(1) + '万'
    return num.toString()
  }

  // 多级菜单分组（父级负责归类，点击父标题展开/折叠子菜单）
  const tabGroups = [
    {
      id: 'group-dashboard', label: '仪表盘', icon: LayoutDashboard,
      tabs: [
        { id: 'dashboard', label: '总览', icon: TrendingUp },
      ],
    },
    {
      id: 'group-trends', label: '内容趋势', icon: LineChart,
      tabs: [
        { id: 'kichu-rank', label: '鬼畜榜', icon: Trophy },
        { id: 'memes', label: '热梗', icon: Flame },
        { id: 'videos', label: '潜力视频', icon: Zap },
      ],
    },
    {
      id: 'group-assets', label: '创作资源', icon: Layers,
      tabs: [
        { id: 'meme-materials', label: '梗素材库', icon: Sparkles },
        { id: 'songs', label: '热歌 BGM', icon: Music },
        { id: 'materials', label: '素材发掘', icon: Search },
      ],
    },
    {
      id: 'group-insight', label: '互动洞察', icon: ScanSearch,
      tabs: [
        { id: 'danmaku', label: '弹幕 & 评论', icon: MessageCircle },
        { id: 'up-trends', label: 'UP 主动态', icon: Users },
      ],
    },
  ]
  // 底部独立入口（不参与折叠展开）
  const devTab = { id: 'dev', label: '开发者后台', icon: Code2 }

  const d = (idx, step = 45) => idx * step

  return (
    <div className="app-shell">
      <Sidebar
        tabGroups={tabGroups} devTab={devTab}
        activeTab={activeTab} onTabChange={setActiveTab}
        onRefresh={handleRefresh} loading={loading} crawling={crawling}
        lastUpdated={data.last_updated} isLive={isLive} liveExpired={liveExpired}
        onToggleFavorites={() => { if (!biliUser) { setShowLogin(true); return } setShowFavorites(v => !v) }} favoritesCount={favorites.length}
        onOpenLogin={() => setShowLogin(true)} biliUser={biliUser} onLogout={handleLogout}
        isAdmin={isAdmin} onAdminLogin={handleAdminLogin}
        onDevBlocked={() => flashNotice('需要管理员权限')}
        theme={theme} onToggleTheme={toggleTheme}
      />

      <main className="flex-1 min-w-0 relative z-10 flex flex-col">
        {activeTab === 'dashboard' && (
          <div className="sr-only">
            <h1>GuichuHub · B站鬼畜创作灵感看板</h1>
            <p>发现鬼畜区排行榜、热梗、热门 BGM、潜力视频与 UP 主动态，寻找二创灵感。</p>
          </div>
        )}
        {activeTab === 'dev' && isAdmin && (
          <Suspense fallback={null}><DevConsole /></Suspense>
        )}
        {activeTab === 'dev' && !isAdmin && <p className="p-8 text-slate-500">需要管理员权限才能访问开发者后台。</p>}

        {activeTab !== 'dev' && (
          <div className="w-full max-w-[1400px] mx-auto px-4 md:px-8 py-6 md:py-10 space-y-10 animate-stagger-in">
            {breakerTrend.length > 0 && (
              <div className="kb-card overflow-hidden">
                <div className="inner px-2 pt-1">
                  <OnlineBreakerChart trend={breakerTrend} threshold={breakerThreshold} />
                </div>
              </div>
            )}

            {loading && (
              <div className="flex items-center justify-center py-24">
                <div className="flex flex-col items-center gap-4">
                  <div className="w-9 h-9 border-[3px] border-primary-500 border-t-transparent rounded-full animate-spin" />
                  <p className="text-xs text-haze-400">数据加载中…</p>
                </div>
              </div>
            )}

            {/* ═══════════ 总览 ═══════════ */}
            {!loading && activeTab === 'dashboard' && (
              <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 lg:gap-8">
                <div className="lg:col-span-8 space-y-10">
                  <Suspense fallback={<LazyFallback />}><BurstingVideos /></Suspense>

                  <Section title="鬼畜区排行榜" icon={<Trophy size={20} className="text-haze-50" />}
                           total={data.kichu_rank?.length} moreText="查看全部" more={() => setActiveTab('kichu-rank')}>
                    <div className="space-y-3">
                      {data.kichu_rank?.slice(0, 3).map((v, i) => (
                        <VideoCard key={v.bvid || i} video={v} index={i} trendColor={trendColor} formatNumber={formatNumber}
                                   onFavorite={() => handleAddFavorite('video', v)} isFavorited={isFav('video', v)} staggerDelay={d(i)} />
                      ))}
                      {data.kichu_rank?.length === 0 && <EmptyHint text="暂无鬼畜区排行数据" />}
                    </div>
                  </Section>

                  <Section title="今日热梗 TOP" icon={<Flame size={20} className="text-neon-rose" />}
                           total={data.hot_memes?.length}>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      {data.hot_memes?.slice(0, 6).map((m, i) => (
                        <MemeCard key={m.keyword || i} meme={m} index={i} trendColor={trendColor} formatNumber={formatNumber}
                                  maxHeat={maxHeat} onFavorite={() => handleAddFavorite('meme', m)} isFavorited={isFav('meme', m)} staggerDelay={d(i)} />
                      ))}
                      {data.hot_memes?.length === 0 && <EmptyHint colSpan={2} text="暂无热梗数据" />}
                    </div>
                  </Section>

                  <Section title="鬼畜潜力视频" icon={<Zap size={20} className="text-primary-500" />}
                           moreText="查看全部" more={() => setActiveTab('videos')}
                           desc="已发布的鬼畜作品中具有爆发潜力的视频，综合批内热度（转发/评论/弹幕密度 × 播放）与互动质量率，乘以新鲜度与同接补正计算潜力指数。">
                    <div className="space-y-3">
                      {data.hot_videos?.slice(0, 4).map((v, i) => (
                        <VideoCard key={v.bvid || i} video={v} index={i} trendColor={trendColor} formatNumber={formatNumber}
                                   onFavorite={() => handleAddFavorite('video', v)} isFavorited={isFav('video', v)} staggerDelay={d(i)} />
                      ))}
                      {data.hot_videos?.length === 0 && <EmptyHint text="暂无潜力视频数据" />}
                    </div>
                  </Section>

                  <Section title="互动质量宝藏视频" icon={<Sparkles size={20} className="text-neon-amber" />}
                           desc={interactionQuality.length > 0 ? '⭐ 表示「低播放 + 高互动」—— 播放低于中位 & 投币率高于中位。综合互动分 = 投币率×3 + 收藏率×2 + 点赞/分享/评论/弹幕率，剔除百万级已火作品，是二创选材的优先目标。' : null}>
                    <div className="space-y-2">
                      {interactionQuality.slice(0, 10).map((v, i) => (
                        <a key={v.bvid} href={`https://www.bilibili.com/video/${v.bvid}`} target="_blank" rel="noopener noreferrer"
                           className="kb-card kb-stagger px-4 py-3 flex items-center gap-3 group"
                           style={{ animationDelay: `${d(i, 35)}ms` }}>
                          <div className="inner w-full flex items-center gap-3">
                            <span className="kb-rank kb-rank--n shrink-0">{i + 1}</span>
                            <div className="flex-1 min-w-0">
                              <p className="text-[0.92rem] font-semibold text-haze-50 truncate leading-snug group-hover:text-primary-500 transition-colors flex items-center gap-1.5">
                                {v.is_treasure && <span title="低播放高互动宝藏视频">⭐</span>}{v.title}
                              </p>
                              <p className="text-xs text-haze-400 truncate mt-0.5">{v.author || '未知UP'} · {v.tname} · {formatNumber(v.views)} 播放</p>
                            </div>
                            <div className="hidden sm:flex items-center gap-1.5 shrink-0">
                              <span className="kb-chip kb-chip--cyan" title="投币率">币 {Number(v.coin_ratio).toFixed(2)}%</span>
                              <span className="kb-chip kb-chip--ghost" title="收藏率">藏 {Number(v.fav_ratio).toFixed(2)}%</span>
                              <span className="kb-chip kb-chip--pink" title="综合互动分">分 {Number(v.engagement_score).toFixed(2)}</span>
                            </div>
                          </div>
                        </a>
                      ))}
                      {interactionQuality.length === 0 && <EmptyHint text="暂无互动质量数据（需最新批次视频观测）" />}
                    </div>
                  </Section>

                  <Section title="素材发掘" icon={<Search size={20} className="text-neon-cyan" />}
                           moreText="查看全部" more={() => setActiveTab('materials')}
                           desc="从音乐区/搞笑区挖掘有潜力被二创成鬼畜的热门素材，按素材热度 × 传播性 × 新鲜度评分，原素材越火二创受众越大。">
                    <div className="space-y-3">
                      {data.material_candidates?.slice(0, 4).map((v, i) => (
                        <VideoCard key={v.bvid || i} video={v} index={i} trendColor={trendColor} formatNumber={formatNumber}
                                   onFavorite={() => handleAddFavorite('video', v)} isFavorited={isFav('video', v)} staggerDelay={d(i)} />
                      ))}
                      {data.material_candidates?.length === 0 && <EmptyHint text="暂无素材发掘数据" />}
                    </div>
                  </Section>
                </div>

                <div className="lg:col-span-4 space-y-8">
                  <Section title="热门BGM" icon={<Music size={20} className="text-primary-500" />}>
                    <div className="kb-card overflow-hidden">
                      <div className="inner divide-y divide-white/5">
                        {data.hot_songs?.slice(0, 5).map((s, i) => (
                          <SongCard key={s.bvid || i} song={s} index={i} trendColor={trendColor} formatNumber={formatNumber}
                                    onFavorite={() => handleAddFavorite('song', s)} isFavorited={isFav('song', s)} staggerDelay={d(i, 50)} />
                        ))}
                        {data.hot_songs?.length === 0 && <div className="p-8 text-center text-xs text-haze-400">暂无BGM数据</div>}
                      </div>
                    </div>
                  </Section>

                  <Section title="弹幕热词" icon={<MessageCircle size={20} className="text-neon-emerald" />}>
                    <DanmakuCloud words={data.danmaku_words || []} />
                  </Section>

                  <Section title="神评论" icon={<Star size={20} className="text-neon-amber" />}>
                    <CommentList comments={(data.comments_gold || []).slice(0, 10)} formatNumber={formatNumber} compact />
                  </Section>
                </div>
              </div>
            )}

            {/* ═══════════ 鬼畜榜 ═══════════ */}
            {!loading && activeTab === 'kichu-rank' && (
              <>
                <PageHeader title="鬼畜区排行榜" icon={<Trophy size={22} className="text-haze-50" />}
                            subtitle="B站鬼畜区最新热门作品，学习对标必看。" />
                <div className="space-y-3">
                  {data.kichu_rank?.map((v, i) => (
                    <VideoCard key={v.bvid || i} video={v} index={i} trendColor={trendColor} formatNumber={formatNumber} showRadar
                               onFavorite={() => handleAddFavorite('video', v)} isFavorited={isFav('video', v)} staggerDelay={d(i)} />
                  ))}
                  {data.kichu_rank?.length === 0 && <EmptyHint text="暂无鬼畜区排行数据" />}
                </div>
              </>
            )}

            {/* ═══════════ 热梗 ═══════════ */}
            {!loading && activeTab === 'memes' && (
              <>
                <PageHeader title="热梗库" icon={<Flame size={22} className="text-haze-50" />}
                            subtitle="从热门视频中提取的关键词梗，按热度排序。" />
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                  {data.hot_memes?.map((m, i) => (
                    <MemeCard key={m.keyword || i} meme={m} index={i} trendColor={trendColor} formatNumber={formatNumber}
                              maxHeat={maxHeat} onFavorite={() => handleAddFavorite('meme', m)} isFavorited={isFav('meme', m)} staggerDelay={d(i, 35)} />
                  ))}
                  {data.hot_memes?.length === 0 && <EmptyHint colSpan={3} text="暂无热梗数据" />}
                </div>
              </>
            )}

            {/* ═══════════ 梗素材库 ═══════════ */}
            {!loading && activeTab === 'meme-materials' && (
              <>
                <PageHeader title="梗素材库" icon={<Sparkles size={22} className="text-haze-50" />}
                            subtitle="热门鬼畜梗专题，每个梗聚合相关视频和 BGM 素材。" />
                <div className="space-y-6">
                  {data.meme_materials?.map((meme, idx) => (
                    <article key={meme.name || idx} className="kb-card kb-stagger overflow-hidden"
                             style={{ animationDelay: `${d(idx, 55)}ms` }}>
                      <div className="relative p-5 md:p-6 bg-gradient-to-r from-primary-500/8 via-transparent to-neon-violet/6 border-b border-white/5">
                        <div className="flex items-start justify-between gap-4">
                          <div>
                            <h3 className="text-[1.15rem] font-bold text-haze-50 flex items-center gap-2.5">
                              <span className="inline-flex items-center justify-center w-9 h-9 rounded-2xl
                                               bg-gradient-to-br from-primary-500 to-bili-dark text-white shadow-glow-pink">
                                <Flame size={17} />
                              </span>{meme.name}
                            </h3>
                            <p className="text-xs text-haze-300 mt-2 max-w-2xl leading-relaxed">{meme.description}</p>
                            <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 mt-3">
                              <span className="kb-chip kb-chip--pink">相关视频 <b className="kb-num ml-1">{meme.video_count}</b> 个</span>
                              <span className="kb-chip kb-chip--cyan">总播放 <b className="kb-num ml-1">{formatNumber(meme.total_views)}</b></span>
                              {meme.aliases?.length > 0 && <span className="kb-chip kb-chip--ghost">别名：{meme.aliases.slice(0, 3).join(' / ')}</span>}
                            </div>
                          </div>
                          <button onClick={() => handleAddFavorite('meme_material', meme)} title="收藏"
                                  className={'kb-icon-btn shrink-0 ' + (isFav('meme_material', meme) ? '!text-primary-500 !bg-primary-50' : '')}>
                            {isFav('meme_material', meme) ? <Star size={19} fill="currentColor" /> : <Star size={19} />}
                          </button>
                        </div>
                      </div>
                      <div className="inner p-5 md:p-6">
                        <h4 className="text-[0.92rem] font-semibold text-haze-100 mb-3 flex items-center gap-2">
                          <Video size={15} className="text-primary-500" />相关视频 ({meme.related_videos?.length || 0})
                        </h4>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                          {meme.related_videos?.slice(0, 6).map((v, i) => (
                            <a key={v.bvid || i} href={`https://www.bilibili.com/video/${v.bvid}`} target="_blank" rel="noopener noreferrer"
                               className="kb-card p-2.5 flex gap-3 group">
                              <div className="inner flex gap-3 w-full">
                                <div className="w-24 h-14 shrink-0 rounded-lg overflow-hidden bg-void-700 relative group/cover">
                                  {v.cover && <img src={`/api/proxy/image?url=${encodeURIComponent(v.cover)}`} alt={v.title}
                                                   className="w-full h-full object-cover group-hover/cover:scale-[1.05] duration-500" />}
                                  <div className="absolute inset-0 bg-black/0 group-hover/cover:bg-black/30 transition-colors flex items-center justify-center">
                                    <div className="w-8 h-8 rounded-full bg-white/95 scale-75 opacity-0 group-hover/cover:scale-100 group-hover/cover:opacity-100 transition-all duration-300 shadow-glow-pink">
                                      <PlayIcon className="w-4 h-4 translate-x-[1px] text-primary-500" />
                                    </div>
                                  </div>
                                </div>
                                <div className="flex-1 min-w-0">
                                  <p className="text-xs font-medium text-haze-50 line-clamp-2 group-hover:text-primary-500 transition-colors leading-snug">{v.title}</p>
                                  <p className="text-[11px] text-haze-400 mt-1 tabular-nums">{formatNumber(v.views)} 播放</p>
                                </div>
                              </div>
                            </a>
                          ))}
                        </div>
                        {meme.related_songs?.length > 0 && (
                          <>
                            <h4 className="text-[0.92rem] font-semibold text-haze-100 mt-6 mb-3 flex items-center gap-2">
                              <Music size={15} className="text-primary-500" />相关 BGM ({meme.related_songs?.length})
                            </h4>
                            <div className="kb-card overflow-hidden">
                              <div className="inner divide-y divide-white/5">
                                {meme.related_songs?.map((song, i) => (
                                  <SongCard key={song.bvid || i} song={song} index={i} trendColor={trendColor} formatNumber={formatNumber}
                                            onFavorite={() => handleAddFavorite('song', song)} isFavorited={isFav('song', song)} staggerDelay={d(i, 30)} />
                                ))}
                              </div>
                            </div>
                          </>
                        )}
                      </div>
                    </article>
                  ))}
                  {data.meme_materials?.length === 0 && <EmptyHint text="暂无梗素材数据" />}
                </div>
              </>
            )}

            {/* ═══════════ 热歌 ═══════════ */}
            {!loading && activeTab === 'songs' && (
              <>
                <PageHeader title="热门BGM库" icon={<Music size={22} className="text-primary-500" />}
                            subtitle="音乐区 + 鬼畜区热门作品，适合做 BGM 的素材。" />
                <div className="kb-card overflow-hidden">
                  <div className="inner divide-y divide-white/5">
                    {data.hot_songs?.map((s, i) => (
                      <SongCard key={s.bvid || i} song={s} index={i} trendColor={trendColor} formatNumber={formatNumber}
                                onFavorite={() => handleAddFavorite('song', s)} isFavorited={isFav('song', s)} staggerDelay={d(i, 30)} />
                    ))}
                    {data.hot_songs?.length === 0 && <div className="p-10 text-center text-xs text-haze-400">暂无BGM数据</div>}
                  </div>
                </div>
              </>
            )}

            {/* ═══════════ 潜力视频 ═══════════ */}
            {!loading && activeTab === 'videos' && (
              <>
                <PageHeader title="鬼畜潜力视频" icon={<Zap size={22} className="text-haze-50" />}
                            subtitle="已发布的鬼畜作品中具有爆发潜力的视频。"
                            note="综合批内相对热度与互动质量率（赞币藏/播放），乘以新鲜度与同接补正计算潜力指数，已剔除百万级以上已火视频与过低播放内容。" />
                <div className="space-y-3">
                  {data.hot_videos?.map((v, i) => (
                    <VideoCard key={v.bvid || i} video={v} index={i} trendColor={trendColor} formatNumber={formatNumber} showRadar
                               onFavorite={() => handleAddFavorite('video', v)} isFavorited={isFav('video', v)} staggerDelay={d(i)} />
                  ))}
                  {data.hot_videos?.length === 0 && <EmptyHint text="暂无潜力视频数据" />}
                </div>
              </>
            )}

            {/* ═══════════ 素材发掘 ═══════════ */}
            {!loading && activeTab === 'materials' && (
              <>
                <PageHeader title="鬼畜素材发掘" icon={<Search size={22} className="text-neon-cyan" />} />
                <div className="space-y-10">
                  <Section title="鬼畜标签热度" icon={<Tag size={18} className="text-neon-amber" />}
                           desc="已发布鬼畜作品的高频标签——⭐ = 该标签下视频平均播放高于全体中位数（市场已验证的爆款方向）。">
                    <div className="kb-card p-5">
                      <div className="inner">
                        {tagHeat.length === 0 ? (
                          <p className="text-xs text-haze-400 text-center py-5">暂无标签数据</p>
                        ) : (
                          <div className="space-y-2">
                            {tagHeat.slice(0, 20).map((t, i) => {
                              const maxCount = Math.max(...tagHeat.map(x => x.count), 1)
                              const barPct = (t.count / maxCount) * 100
                              return (
                                <div key={t.tag} className="flex items-center gap-3">
                                  <span className="w-6 text-xs text-haze-400 text-right tabular-nums">{i + 1}</span>
                                  <span className="w-24 max-w-24 truncate text-xs font-medium text-haze-100" title={t.tag}>{t.tag}</span>
                                  <div className="flex-1 h-5 bg-void-800/60 rounded-lg overflow-hidden">
                                    <div className={`h-full rounded-lg transition-all duration-700 ease-out ${
                                      t.is_hot ? 'kb-bar--hot' : 'kb-bar--cool'
                                    }`} style={{ width: `${Math.max(barPct, 3)}%` }} />
                                  </div>
                                  {/* 右侧指标使用固定三列；无星标时也保留占位，避免各行轨道和数字错位。 */}
                                  <div className="grid grid-cols-[3.5rem_5rem_1rem] items-center gap-2 flex-shrink-0">
                                    <span className="text-xs text-haze-400 text-right tabular-nums">{t.count}部</span>
                                    <span className={`text-xs text-right tabular-nums ${t.is_hot ? 'font-semibold text-neon-amber' : 'text-haze-300'}`}>
                                      {formatNumber(t.avg_views)}均播
                                    </span>
                                    <span
                                      className={`text-xs text-center ${t.is_hot ? '' : 'invisible'}`}
                                      title={t.is_hot ? '平均播放高于中位数' : undefined}
                                      aria-hidden={!t.is_hot}
                                    >
                                      ⭐
                                    </span>
                                  </div>
                                </div>
                              )
                            })}
                          </div>
                        )}
                      </div>
                    </div>
                  </Section>

                  <Section title="鬼畜素材相关视频" icon={<Search size={18} className="text-neon-cyan" />}
                           total={data.material_candidates?.length}
                           desc="从音乐区/搞笑区挖掘有潜力被二创成鬼畜的热门素材。按素材热度 × 传播性 × 新鲜度评分；不设播放上限、不用同接补正，时效窗口 60 天。">
                    <div className="space-y-3">
                      {data.material_candidates?.map((v, i) => (
                        <VideoCard key={v.bvid || i} video={v} index={i} trendColor={trendColor} formatNumber={formatNumber}
                                   onFavorite={() => handleAddFavorite('video', v)} isFavorited={isFav('video', v)} staggerDelay={d(i)} />
                      ))}
                      {data.material_candidates?.length === 0 && <EmptyHint text="暂无素材发掘数据" />}
                    </div>
                  </Section>
                </div>
              </>
            )}

            {/* ═══════════ 弹幕 & 评论 ═══════════ */}
            {!loading && activeTab === 'danmaku' && (
              <div className="space-y-10 max-w-6xl">
                <Section title="弹幕热词升温榜" icon={<TrendingUp size={20} className="text-neon-rose" />}
                         subtitle={`最近 ${risingMeta?.recent_batch_count || 2} 批 vs 此前 ${risingMeta?.base_batch_count || 6} 批`}
                         desc="按每批每万词出现率计算，降低抓取量和缺失批次对升温倍率的干扰。">
                  <div className="kb-card p-5">
                    <div className="inner">
                      {risingMeta?.is_stale && (
                        <div className="mb-3 flex items-center gap-2 rounded-lg border border-neon-amber/25 bg-neon-amber/10 px-3 py-2 text-xs text-neon-amber">
                          <AlertTriangle size={14} />
                          最近弹幕词观测距今 {risingMeta.data_age_hours} 小时，榜单仅供历史参考。
                        </div>
                      )}
                      {risingWords.length === 0 ? (
                        <p className="text-xs text-haze-400 text-center py-5">暂无升温词数据（需积累足够观测批次）</p>
                      ) : (
                        <div className="space-y-2">
                          {risingWords.slice(0, 20).map((w, i) => {
                            const maxCount = Math.max(...risingWords.map(x => x.recent_count), 1)
                            const barPct = (w.recent_count / maxCount) * 100
                            const chipCls = w.growth_ratio >= 5 ? 'kb-chip kb-chip--rose' : w.growth_ratio >= 3 ? 'kb-chip kb-chip--pink' : 'kb-chip kb-chip--amber'
                            return (
                              <div key={w.word} className="flex items-center gap-3">
                                <span className="w-6 text-xs text-haze-400 text-right tabular-nums">{i + 1}</span>
                                <span className="w-24 max-w-24 truncate text-xs font-medium text-haze-100" title={w.word}>{w.word}</span>
                                <div className="flex-1 h-5 bg-void-800/60 rounded-lg overflow-hidden">
                                  <div className="h-full rounded-lg transition-all duration-700 ease-out kb-bar--hot" style={{ width: `${Math.max(barPct, 3)}%` }} />
                                </div>
                                <span className="w-16 text-xs text-haze-400 text-right tabular-nums" title={`近期每万词出现 ${w.recent_rate} 次`}>{w.recent_count}次/批</span>
                                <span className="w-16 text-xs text-haze-500 text-right tabular-nums" title={`基准每万词出现 ${w.base_rate} 次`}>{w.base_count}次/批</span>
                                <span className={chipCls} title={`标准化出现率为基准期的 ${w.growth_ratio} 倍`}>{w.is_new ? '新词' : `↑${w.growth_ratio}x`}</span>
                              </div>
                            )
                          })}
                        </div>
                      )}
                    </div>
                  </div>
                </Section>

                <Section title="弹幕热词云" icon={<MessageCircle size={20} className="text-neon-emerald" />}
                         desc="从热门内容中分析出的高频弹幕词汇，悬停词汇可屏蔽。">
                  <DanmakuCloud words={data.danmaku_words || []} large />
                </Section>

                <Section title="神评论精选" icon={<Star size={20} className="text-neon-amber" />}
                         desc="热门视频中的高赞评论，可能是下一个梗的来源。">
                  <CommentList comments={data.comments_gold || []} formatNumber={formatNumber} />
                </Section>
              </div>
            )}

            {/* ═══════════ UP主动态 ═══════════ */}
            {!loading && activeTab === 'up-trends' && (
              <Suspense fallback={<LazyFallback />}><UpTrends formatNumber={formatNumber} isAdmin={isAdmin} /></Suspense>
            )}
          </div>
        )}
        <SiteFooter
          tabGroups={tabGroups}
          activeTab={activeTab}
          onNavigate={(tabId) => { setActiveTab(tabId); window.scrollTo({ top: 0, behavior: 'smooth' }) }}
        />
      </main>

      {showFavorites && (
        <FavoritesPanel favorites={favorites} onClose={() => setShowFavorites(false)}
                        onRemove={handleRemoveFavorite} formatNumber={formatNumber} onRefresh={loadFavorites} />
      )}
      {showLogin && (
        <BilibiliLogin onClose={() => setShowLogin(false)} onLoginSuccess={handleLoginSuccess} />
      )}
      <MiniPlayer />
    </div>
  )
}

function Section({ title, icon, subtitle, desc, note, total, more, moreText, children }) {
  return (
    <section>
      <div className="flex items-baseline justify-between gap-3 mb-4 md:mb-5">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2.5">
            {/* icon 扁平直接出现，不再用圆角矩形底包裹；
                颜色保持调用方传入的 className（鬼畜区排行榜 Trophy 传 text-haze-50 即白色）。 */}
            {icon}
            <h2 className="kb-section-title text-[1.08rem] md:text-[1.18rem] font-bold text-haze-50 leading-none">{title}</h2>
            {total != null && <span className="kb-chip kb-chip--ghost">共 {total} 条</span>}
            {subtitle && <span className="text-xs text-haze-400 ml-1 hidden md:inline">· {subtitle}</span>}
          </div>
          {(desc || note) && (
            <p className="text-xs text-haze-400 mt-2.5 ml-[42px] leading-relaxed max-w-3xl">
              {note && <span className="kb-chip kb-chip--ghost mr-2">说明</span>}{desc}
            </p>
          )}
        </div>
        {more && (
          <button onClick={more} className="kb-chip text-primary-600 bg-primary-50 border border-primary-200 hover:bg-primary-100 transition shrink-0 cursor-pointer">
            {moreText || '查看更多'} →
          </button>
        )}
      </div>
      {children}
    </section>
  )
}

function PageHeader({ title, icon, subtitle, note }) {
  return (
    <div className="kb-stagger pb-1">
      <div className="flex items-center gap-3 mb-2">
        {/* icon 扁平直接出现，不再用渐变圆角矩形底包裹；颜色由调用方 className 决定 */}
        {icon}
        <div>
          <h1 className="text-[1.45rem] md:text-[1.6rem] font-bold text-haze-50 leading-tight">{title}</h1>
        </div>
      </div>
      {subtitle && (
        <p className="text-xs text-haze-400 ml-[34px] leading-relaxed">
          {note && <span className="kb-chip kb-chip--ghost mr-2">提示</span>}{subtitle}
        </p>
      )}
    </div>
  )
}

function EmptyHint({ text, colSpan = 1 }) {
  return (
    <div className="kb-card p-10 flex flex-col items-center gap-3 text-center"
         style={{ gridColumn: colSpan > 1 ? `span ${colSpan}` : undefined }}>
      <div className="inner flex flex-col items-center gap-3">
        <div className="w-14 h-14 rounded-2xl flex items-center justify-center bg-gradient-to-br from-white/5 to-primary-500/5">
          <Sparkles size={22} className="text-haze-500" />
        </div>
        <p className="text-xs text-haze-400">{text}</p>
      </div>
    </div>
  )
}

function PlayIcon({ className }) {
  return (<svg viewBox="0 0 24 24" fill="currentColor" className={className}><path d="M8 5v14l11-7z" /></svg>)
}
