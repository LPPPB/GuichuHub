import { createHash } from 'node:crypto'
import { PUBLIC_ROUTES, routeForTab } from '../src/routing/publicRoutes.js'
import { validateBootstrap } from '../src/publicPages/contract.js'

const tag = html => `"${createHash('sha256').update(html).digest('hex')}"`
export function createPublisher({fetchSections,renderPage,cache,clock=()=>Math.floor(Date.now()/1000),buildId,timeoutMs=10_000}) {
  let pages=new Map(),sections={},confirmed={},restored=false,inFlight=null
  const bootstrapFor=(tab,all,times)=>({schema_version:1,build_id:buildId,tab_id:tab,sections:tab==='dashboard'?all:{[tab]:all[tab]},confirmed_at:tab==='dashboard'?times:{[tab]:times[tab]},render_year:new Date().getFullYear()})
  async function render(route,all,times) {
    const bootstrap=bootstrapFor(route.tabId,all,times)
    if (!validateBootstrap(bootstrap)) throw Error('Invalid public content')
    const html=await renderPage({route,bootstrap})
    return {html,etag:tag(html),bootstrap}
  }
  async function restore() {
    if (restored) return
    restored=true
    const saved=await cache.load()
    const candidates=new Map()
    for (const [path,page] of saved) {
      if (!validateBootstrap(page.bootstrap) || !PUBLIC_ROUTES.some(r=>r.path===path && r.tabId===page.bootstrap.tab_id)) continue
      Object.assign(sections,page.bootstrap.sections)
      Object.assign(confirmed,page.bootstrap.confirmed_at)
      if (page.bootstrap.build_id===buildId && tag(page.html)===page.etag) candidates.set(path,page)
    }
    // Rebuild old documents using their compatible public data, never old assets.
    for (const route of PUBLIC_ROUTES) {
      if (!candidates.has(route.path) && (route.tabId==='dashboard'?Object.keys(sections).length:sections[route.tabId])) {
        try { candidates.set(route.path,await render(route,sections,confirmed)) } catch { /* No valid page yet. */ }
      }
    }
    if (candidates.size) {
      await cache.commitBatch(candidates)
      pages=candidates
    }
  }
  async function run() {
    const result={changedPaths:[],retainedPaths:[],failures:[]}
    try { await restore() } catch { result.failures.push('restore') }
    const controller=new AbortController()
    let timer
    let input
    try {
      input=await Promise.race([
        fetchSections({signal:controller.signal}),
        new Promise((_,reject)=>{timer=setTimeout(()=>{controller.abort();reject(Error('timeout'))},timeoutMs)}),
      ])
      if (input?.schema_version!==1 || !input.sections || typeof input.sections!=='object') throw Error('Invalid export')
    } catch { result.failures.push('fetch');result.retainedPaths=[...pages.keys()];return result }
    finally { clearTimeout(timer) }
    for (const [tab,section] of Object.entries(input.sections)) {
      const route=routeForTab(tab)
      if (!route || tab==='dashboard' || !['ready','empty'].includes(section?.status)) continue
      if (sections[tab]?.content_version===section.content_version && pages.has(route.path)) continue
      const nextSections={...sections,[tab]:section}
      const nextConfirmed={...confirmed,[tab]:sections[tab]?.content_version===section.content_version?confirmed[tab]:clock()}
      try {
        const candidate=new Map(pages)
        candidate.set(route.path,await render(route,nextSections,nextConfirmed))
        candidate.set('/',await render(routeForTab('dashboard'),nextSections,nextConfirmed))
        await cache.commitBatch(candidate)
        pages=candidate;sections=nextSections;confirmed=nextConfirmed
        result.changedPaths.push(route.path,'/')
      } catch { result.failures.push(tab) }
    }
    result.changedPaths=[...new Set(result.changedPaths)]
    result.retainedPaths=[...pages.keys()].filter(path=>!result.changedPaths.includes(path))
    return result
  }
  return {
    snapshot:()=>new Map(pages),
    refresh() {
      if (!inFlight) inFlight=run().finally(()=>{inFlight=null})
      return inFlight
    },
  }
}
