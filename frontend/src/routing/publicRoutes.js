export const PUBLIC_ROUTES = [
  {tabId: 'dashboard', path: '/', title: 'GuichuHub · B站鬼畜创作灵感看板'},
  {tabId: 'kichu-rank', path: '/rankings/kichu', title: '鬼畜区排行榜'},
  {tabId: 'memes', path: '/memes', title: '热梗'},
  {tabId: 'videos', path: '/rankings/potential', title: '潜力视频'},
  {tabId: 'meme-materials', path: '/meme-materials', title: '梗素材库'},
  {tabId: 'songs', path: '/bgm', title: '热歌 BGM'},
  {tabId: 'materials', path: '/materials', title: '素材发掘'},
  {tabId: 'danmaku', path: '/insights/discussion', title: '弹幕 & 评论'},
  {tabId: 'up-trends', path: '/up-trends', title: 'UP 主动态'},
]
export function resolvePublicPath(pathname) {
  const route = PUBLIC_ROUTES.find(route => route.path === pathname)
  if (route) return {kind: 'page', route}
  const canonical = PUBLIC_ROUTES.find(route => route.path !== '/' && `${route.path}/` === pathname)
  return canonical ? {kind: 'redirect', location: canonical.path} : {kind: 'not-found'}
}
export const routeForTab = tabId => PUBLIC_ROUTES.find(route => route.tabId === tabId)
