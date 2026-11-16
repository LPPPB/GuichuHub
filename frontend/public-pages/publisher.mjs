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
    const saved=await cache.load()
    const candidates=new Map()
    for (const [path,page] of saved) {
      if (!validateBootstrap(page.bootstrap) || !PUBLIC_ROUTES.some(r=>r.path===path && r.tabId===page.bootstrap.tab_id)) continue
      Object.assign(sections,page.bootstrap.sections)
      Object.assign(confirmed,page.bootstrap.confirmed_at)
      if (page.bootstrap.build_id===buildId && tag(page.html)===page.etag) candidates.set(path,page)
    }
    // Already committed matching documents need no new write to remain usable.
    pages=new Map(candidates)
    let rebuilt=false
    // Rebuild old documents using their compatible public data, never old assets.
    for (const route of PUBLIC_ROUTES) {
      if (!candidates.has(route.path) && (route.tabId==='dashboard'?Object.keys(sections).length:sections[route.tabId])) {
        try { candidates.set(route.path,await render(route,sections,confirmed));rebuilt=true } catch { /* No valid page yet. */ }
      }
    }
    if (rebuilt) {
      await cache.commitBatch(candidates)
      pages=candidates
    }
    restored=true
  }
  async function run() {
    const result={changedPaths:[],retainedPaths:[],failures:[],validatedTabs:[]}
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
    const paired=['memes','meme-materials']
    const hasReview=paired.some(tab=>input.sections[tab]?.publication_id)
    if(hasReview) {
      try {
        const id=input.sections.memes?.publication_id
        if(!id || !paired.every(tab=>input.sections[tab]?.publication_id===id && ['ready','empty'].includes(input.sections[tab]?.status)))throw Error('Incomplete review generation')
        const nextSections={...sections},nextConfirmed={...confirmed},candidate=new Map(pages)
        for(const tab of paired) {
          nextSections[tab]=input.sections[tab]
          nextConfirmed[tab]=sections[tab]?.content_version===input.sections[tab].content_version?confirmed[tab]:clock()
        }
        if(paired.some(tab=>sections[tab]?.content_version!==input.sections[tab].content_version || !pages.has(routeForTab(tab).path))) {
          for(const tab of paired)candidate.set(routeForTab(tab).path,await render(routeForTab(tab),nextSections,nextConfirmed))
          candidate.set('/',await render(routeForTab('dashboard'),nextSections,nextConfirmed))
          await cache.commitBatch(candidate)
          pages=candidate;sections=nextSections;confirmed=nextConfirmed
          result.changedPaths.push('/memes','/meme-materials','/')
        }
        result.validatedTabs.push(...paired)
      } catch { result.failures.push('meme-publication') }
    }
    for (const [tab,section] of Object.entries(input.sections)) {
      if(hasReview && paired.includes(tab))continue
      const route=routeForTab(tab)
      if (!route || tab==='dashboard' || !['ready','empty'].includes(section?.status)) continue
      if (sections[tab]?.content_version===section.content_version && pages.has(route.path)) {
        result.validatedTabs.push(tab)
        continue
      }
      const nextSections={...sections,[tab]:section}
      const nextConfirmed={...confirmed,[tab]:sections[tab]?.content_version===section.content_version?confirmed[tab]:clock()}
      try {
        const candidate=new Map(pages)
        candidate.set(route.path,await render(route,nextSections,nextConfirmed))
        candidate.set('/',await render(routeForTab('dashboard'),nextSections,nextConfirmed))
        await cache.commitBatch(candidate)
        pages=candidate;sections=nextSections;confirmed=nextConfirmed
        result.changedPaths.push(route.path,'/')
        result.validatedTabs.push(tab)
      } catch { result.failures.push(tab) }
    }
    result.changedPaths=[...new Set(result.changedPaths)]
    result.retainedPaths=[...pages.keys()].filter(path=>!result.changedPaths.includes(path))
    return result
  }
  function refresh({afterCurrent=false}={}) {
    // An older poll may already have read the rules before this request began.
    if(afterCurrent && inFlight)return inFlight.then(()=>refresh())
    if (!inFlight) inFlight=run().finally(()=>{inFlight=null})
    return inFlight
  }
  return {snapshot:()=>new Map(pages),refresh}
}
