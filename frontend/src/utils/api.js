const API_BASE = '/api'
const TOKEN_KEY = 'kichu_write_token'
const VISITOR_KEY = 'kichu_visitor_id'
const SESSION_KEY = 'kichu_session_token'

// 读取已保存的写操作口令（空串 = 未设置）
export function getWriteToken() {
  try {
    return localStorage.getItem(TOKEN_KEY) || ''
  } catch {
    return ''
  }
}

// B站身份会话 token（扫码登录成功后由后端签发）。
// 凭证（SESSDATA 等）只存服务器会话表，浏览器仅持有此 token。
export function getSessionToken() {
  try {
    return localStorage.getItem(SESSION_KEY) || ''
  } catch {
    return ''
  }
}

export function setSessionToken(token) {
  try {
    if (token) localStorage.setItem(SESSION_KEY, token)
    else localStorage.removeItem(SESSION_KEY)
  } catch { /* 隐私模式等场景忽略 */ }
}

// 访客身份：浏览器本地 UUID（收藏归属标识；清浏览器数据/换设备 = 换新身份）
export function getVisitorId() {
  try {
    let vid = localStorage.getItem(VISITOR_KEY)
    if (vid) return vid
    vid = (window.crypto && window.crypto.randomUUID)
      ? window.crypto.randomUUID()
      : 'v-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 14)
    localStorage.setItem(VISITOR_KEY, vid)
    return vid
  } catch {
    return 'anonymous'
  }
}

// 管理员凭证静默校验：启动时用（不弹窗）。服务端明确拒绝(401)时清除本地失效凭证。
export async function verifyAdminSilent() {
  const token = getWriteToken()
  if (!token) return false
  try {
    const res = await fetch(`${API_BASE}/auth/verify`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Write-Token': token },
    })
    if (res.ok) return true
    if (res.status === 401) localStorage.removeItem(TOKEN_KEY)
    return false
  } catch {
    return false
  }
}

// 弹窗输入口令；返回 null 表示用户取消
function askWriteToken(prev) {
  const hint = prev ? '口令错误，请重新输入（查看后端终端打印的令牌）' : '该操作需要写口令（查看后端终端打印的令牌）'
  const input = window.prompt(hint, '')
  if (input === null) return null // 用户取消
  const t = input.trim()
  if (t) localStorage.setItem(TOKEN_KEY, t)
  return t || null
}

async function doFetch(url, options, headers) {
  const { timeout = 15000, ...rest } = options
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeout)
  try {
    const res = await fetch(`${API_BASE}${url}`, { ...rest, headers, signal: controller.signal })
    clearTimeout(timer)
    // 防御空 body（后端重启瞬间或连接中断可能返回空响应）
    const text = await res.text()
    if (!text) {
      return { res: null, body: { success: false, data: [], message: '服务器返回空响应，请稍后重试' } }
    }
    try {
      return { res, body: JSON.parse(text) }
    } catch (e) {
      // 非 JSON 响应（如网关/代理层返回纯文本错误）：保留 res 供调用方判断
      // 状态码（401 口令弹窗依赖 res.status），body 带原始文本便于排查
      return { res, body: { success: false, data: [], message: `服务器响应异常（HTTP ${res.status}）：${text.slice(0, 120)}` } }
    }
  } catch (e) {
    clearTimeout(timer)
    return { res: null, body: { success: false, data: [], message: e.name === 'AbortError' ? '请求超时' : e.message } }
  }
}

async function request(url, options = {}) {
  const method = (options.method || 'GET').toUpperCase()
  const isWrite = method === 'POST' || method === 'PUT' || method === 'DELETE'
  let token = getWriteToken()

  // 写请求：无口令/口令错误时弹窗输入后重试一次（避免无限弹窗）
  for (let attempt = 0; attempt < 2; attempt++) {
    // 身份凭证跟随所有请求（GET 也携带）：
    //   X-Visitor-Id    → 访客收藏归属（浏览器 UUID）
    //   X-Write-Token   → 超管口令（应急后门；GET /api/favorites 归属、管理员接口均需）
    //   X-Session-Token → B站身份会话（扫码登录签发；管理员名单判定用）
    const headers = { 'Content-Type': 'application/json', ...options.headers, 'X-Visitor-Id': getVisitorId() }
    if (token) headers['X-Write-Token'] = token
    const sessionToken = getSessionToken()
    if (sessionToken) headers['X-Session-Token'] = sessionToken
    const { res, body } = await doFetch(url, options, headers)
    if (isWrite && res && res.status === 401) {
      const t = askWriteToken(!!token)
      if (!t) return { success: false, data: [], message: '写操作口令缺失或错误' }
      token = t
      continue
    }
    return body
  }
  return { success: false, data: [], message: '写操作口令缺失或错误' }
}

export const api = {
  getDashboard: () => request('/dashboard'),
  // 管理员登录（交互式：401 弹窗重试由 request() 内建处理）
  adminLogin: () => request('/auth/verify', { method: 'POST' }),
  refresh: () => request('/refresh', { method: 'POST' }),
  getStatus: () => request('/status'),
  // 三态身份查询（启动/登录后刷新）：data = {admin, via, user}
  getAuthMe: () => request('/auth/me'),
  // 管理员名单（B站账号判定）：{accounts, recent_logins}
  adminAccounts: () => request('/admin/accounts'),
  addAdminAccount: (mid, name = '') =>
    request('/admin/accounts', { method: 'POST', body: JSON.stringify({ mid, name }) }),
  removeAdminAccount: (mid) => request(`/admin/accounts/${mid}`, { method: 'DELETE' }),
  getFavorites: (type, tag) => {
    const params = new URLSearchParams()
    if (type) params.set('type', type)
    if (tag) params.set('tag', tag)
    const query = params.toString()
    return request(`/favorites${query ? '?' + query : ''}`)
  },
  addFavorite: (type, item) =>
    request('/favorites', {
      method: 'POST',
      body: JSON.stringify({ type, item }),
    }),
  removeFavorite: (id) =>
    request(`/favorites/${id}`, { method: 'DELETE' }),
  updateFavorite: (id, data) =>
    request(`/favorites/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),
  // 身份登录（全员开放）：成功响应含 session_token/user/is_admin；
  // token 落 localStorage，B站凭证只留服务器
  getQrcode: () => request('/bili-auth/qrcode'),
  checkLogin: async (key) => {
    const body = await request(`/bili-auth/check?key=${key}`)
    if (body && body.success && body.session_token) setSessionToken(body.session_token)
    return body
  },
  // 采集账号信息 / 采集登录（管理员专属：凭证写入服务器爬虫 Cookie 文件）
  getUserInfo: () => request('/bili-auth/user'),
  collectLogin: () => request('/bili-auth/collect-login'),
  collectCheck: (key) => request(`/bili-auth/collect-check?key=${key}`),
  collectLogout: () => request('/bili-auth/collect-logout', { method: 'POST' }),
  // 退出身份登录：销毁服务器会话；本地 token 无论成败都清除（会话可能已过期）
  logout: async () => {
    const body = await request('/bili-auth/logout', { method: 'POST' })
    setSessionToken('')
    return body
  },
  // UP主动态新接口
  upTrendsCheck: () => request('/up-trends/check'),
  upTrendsList: () => request('/up-trends/list', { timeout: 60000 }),
  upTrendsSaveList: (ups) => request('/up-trends/list', { method: 'POST', body: JSON.stringify({ ups }) }),
  upTrendsExportList: () => `${API_BASE}/up-trends/list/export`,
  upTrendsImportList: (ups) => request('/up-trends/list/import', { method: 'POST', body: JSON.stringify({ ups }) }),
  upTrendsRefresh: () => request('/up-trends/refresh', { method: 'POST', timeout: 180000 }),
  upTrendsAnalysis: () => request('/up-trends/analysis'),
  upTrendsHistory: () => request('/up-trends/history'),
  upTrendsProgress: (taskId) => request(`/up-trends/progress?task_id=${taskId}`),
  // UP 卡片数据（词云 + 分区标签 + 统计，列表内联标签/悬停弹窗共用）
  getUpCard: (mid) => request(`/up-trends/up-card/${mid}`, { timeout: 60000 }),
  // 视频观测时序（VideoCard 折线图，按需加载）
  getVideoObsTrend: (bvid, hours = 48) => request(`/videos/${bvid}/obs-trend?hours=${hours}`),
  // 视频 AI 总结（B站官方 AI 摘要 + 大纲）
  getVideoConclusion: (bvid) => request(`/videos/${bvid}/conclusion`),
  // 播放增速榜 / 爆发预警（总览页，仅 hot tier）
  getBurstingVideos: (window = 2, threshold = 2.0, limit = 40) =>
    request(`/bursting-videos?window=${window}&threshold=${threshold}&limit=${limit}`),
  // 互动质量榜：低播放高互动的宝藏视频（选材信号）
  getInteractionQuality: (limit = 20) => request(`/videos/interaction-quality?limit=${limit}`),
  // 发布习惯：按小时/星期聚合发布量与平均播放
  getPublishHabits: (days = 180) => request(`/up-trends/publish-habits?days=${days}`),
  getCalendar: (year) => request(`/up-trends/calendar?year=${year}`),
  getCalendarRecent: (days = 60) => request(`/up-trends/calendar/recent?days=${days}`),
  // 日历某天发布的视频列表（YYYY-MM-DD）
  getCalendarDayVideos: (date, limit = 50) =>
    request(`/up-trends/calendar/day?date=${date}&limit=${limit}`),
  // 手动回填：近期窗口或指定年份。返回持久化 job_id。
  calendarBackfill: ({ mode, days, year }) =>
    request('/up-trends/calendar/backfill', {
      method: 'POST',
      body: JSON.stringify({ mode, ...(days ? { days } : {}), ...(year ? { year } : {}) }),
    }),
  getCalendarJob: (jobId) => request(`/up-trends/calendar/jobs/${jobId}`),
  getActiveCalendarJob: () => request('/up-trends/calendar/jobs/active'),
  retryCalendarJob: (jobId) => request(`/up-trends/calendar/jobs/${jobId}/retry`, { method: 'POST' }),
  // 涨粉榜：最新批次 vs 窗口起点批次的粉丝数差值
  getFollowerGrowth: (days = 7, limit = 10) =>
    request(`/up-trends/follower-growth?days=${days}&limit=${limit}`),
  // 高增速视频榜：追踪 UP 主视频中播放量增速最快的（跨批次快照对比）
  getUpTrendsHotGrowth: (lookback = 14, limit = 10) =>
    request(`/up-trends/hot-growth?lookback=${lookback}&limit=${limit}`),
  // UP追踪申请（访客提交 / 站长审核，方案C 多用户）
  searchUps: (keyword) => request(`/up-trends/search?keyword=${encodeURIComponent(keyword)}`),
  getObservationRoster: () => request('/up-trends/roster'),
  getObservationManagement: () => request('/up-trends/roster/manage'),
  submitUpRequest: (mid, reason = '', request_type = 'add') =>
    request('/up-trends/requests', { method: 'POST', body: JSON.stringify({ mid, reason, request_type }) }),
  getMyUpRequests: () => request('/up-trends/requests/mine'),
  withdrawUpRequest: (id) => request(`/up-trends/requests/${id}/withdraw`, { method: 'POST' }),
  adminGetUpRequests: () => request('/up-trends/requests'),
  reviewUpRequest: (id, action, reason = '') =>
    request(`/up-trends/requests/${id}/review`, { method: 'POST', body: JSON.stringify({ action, reason }) }),
  // 标签热度：鬼畜分区标签频次 + 平均播放，爆款标签标记
  getTagHeat: (limit = 30) => request(`/videos/tag-heat?limit=${limit}`),
  // 弹幕热词升温榜：最近完整批次 vs 此前基准批次（按每万词出现率归一化）
  getRisingWords: (recentBatches = 2, baseBatches = 6, limit = 30) =>
    request(`/danmaku/rising-words?recent_batches=${recentBatches}&base_batches=${baseBatches}&limit=${limit}`),
  // 开发者模式：梗素材库停用词表
  getMemeStopwords: () => request('/config/meme-stopwords'),
  saveMemeStopwords: (categories) =>
    request('/config/meme-stopwords', { method: 'PUT', body: JSON.stringify({ categories }) }),
  // 开发者模式：梗素材库种子热梗词
  getMemeSeedWords: () => request('/config/meme-seed-words'),
  saveMemeSeedWords: (words) =>
    request('/config/meme-seed-words', { method: 'PUT', body: JSON.stringify({ words }) }),
  // 开发者后台：标签过滤词表（is_useless_tag 共享：分类停用词/广告品牌/活动词/二字白名单）
  getTagFilters: () => request('/config/tag-filters'),
  saveTagFilters: (filters) =>
    request('/config/tag-filters', { method: 'PUT', body: JSON.stringify(filters) }),
  // 开发者后台：弹幕热词过滤词表（filter_danmaku_words 共享：精确匹配 + 子串匹配）
  getDanmakuFilters: () => request('/config/danmaku-filters'),
  saveDanmakuFilters: (filters) =>
    request('/config/danmaku-filters', { method: 'PUT', body: JSON.stringify(filters) }),
  getWordRulesOverview: () => request('/config/word-rules/overview'),
  testWordRules: (text) =>
    request('/config/word-rules/test', { method: 'POST', body: JSON.stringify({ text }) }),
  // 开发者后台：回测面板（历史批次 + 运行回测）
  getDevBacktestBatches: () => request('/dev/backtest/batches'),
  runDevBacktest: (ts, window, topN) =>
    request(`/dev/backtest/run?ts=${ts}&window=${window}&top_n=${topN}`, { timeout: 60000 }),
  // 开发者后台：数据体检
  getDevStats: () => request('/dev/stats'),
}
