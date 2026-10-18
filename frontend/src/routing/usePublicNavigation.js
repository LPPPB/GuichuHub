import { useCallback, useEffect, useState } from 'react'
import { resolvePublicPath, routeForTab } from './publicRoutes'

function currentTab() {
  if (typeof window === 'undefined') return 'dashboard'
  const result = resolvePublicPath(window.location.pathname)
  return result.route?.tabId || (result.kind === 'redirect' ? resolvePublicPath(result.location).route.tabId : 'not-found')
}
export function usePublicNavigation(initialTab) {
  const [activeTab, setActiveTab] = useState(() => initialTab || currentTab())
  const navigate = useCallback(tabId => {
    const route = routeForTab(tabId)
    if (!route && tabId !== 'dev') return
    if (route && window.location.pathname !== route.path) window.history.pushState({}, '', route.path)
    setActiveTab(tabId)
  }, [])
  useEffect(() => {
    const route = routeForTab(activeTab)
    if (!route) return
    document.title = route.tabId === 'dashboard' ? route.title : `${route.title} · GuichuHub`
    let canonical = document.querySelector('link[rel="canonical"]')
    if (!canonical) {
      canonical = document.createElement('link')
      canonical.rel = 'canonical'
      document.head.append(canonical)
    }
    canonical.href = `https://guichuhub.cn${route.path}`
  }, [activeTab])
  useEffect(() => {
    const result = resolvePublicPath(window.location.pathname)
    if (result.kind === 'redirect') window.history.replaceState({}, '', result.location + window.location.search)
    const onPop = () => setActiveTab(currentTab())
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])
  return {activeTab, navigate}
}
