import assert from 'node:assert/strict'
import {readFile} from 'node:fs/promises'
import {chromium} from 'playwright-core'
import {renderPublicPage,PUBLIC_ROUTES} from '../dist-server/ssr.mjs'

// Production client + SSR with synthetic data. Slow public chunks must not let
// fast preference/API effects discard a still-hydrating Suspense boundary.
const fixture=JSON.parse(await readFile(new URL('../../ops/public-pages-test/fixtures.json',import.meta.url),'utf8'))
fixture.sections['up-trends'].data.up_analysis.analysis.keyword_cloud.push({text:'合成公开次级热词',value:21})
const template=await readFile(new URL('../dist-server/template.html',import.meta.url),'utf8')
const dashboard=Object.assign({},...Object.entries(fixture.sections).filter(([tab])=>tab!=='up-trends').map(([,section])=>section.data))
const browser=await chromium.launch({headless:true,...(process.env.LAYOUT_BROWSER_CHANNEL?{channel:process.env.LAYOUT_BROWSER_CHANNEL}:{})})
try {
  for(const tab of ['dashboard','up-trends']) {
    const route=PUBLIC_ROUTES.find(route=>route.tabId===tab)
    const bootstrap={schema_version:1,build_id:'hydration-regression',tab_id:tab,sections:fixture.sections,confirmed_at:{},render_year:2026}
    const html=await renderPublicPage({route,bootstrap,template})
    const context=await browser.newContext({viewport:{width:1440,height:1000}})
    await context.addInitScript(()=>localStorage.setItem('kb-theme','light'))
    const page=await context.newPage(),errors=[]
    page.on('pageerror',error=>errors.push(error.message))
    page.on('console',message=>{if(message.type()==='error' && /hydration|hydrating|Minified React error/i.test(message.text()))errors.push(message.text())})
    await page.route('**/*',async request=>{
      const url=new URL(request.request().url())
      if(url.hostname!=='hydration.test')return request.abort()
      if(url.pathname.startsWith('/api/')){
        const data=url.pathname==='/api/dashboard'?dashboard:
          url.pathname==='/api/up-trends/analysis'?fixture.sections['up-trends'].data.up_analysis:
          url.pathname==='/api/auth/me'?{admin:false,user:null}:[]
        return request.fulfill({json:{success:true,data}})
      }
      if(url.pathname.startsWith('/assets/')){
        if(/\/(UpTrends|BurstingVideos)-/.test(url.pathname))await new Promise(resolve=>setTimeout(resolve,1500))
        const asset=new URL('../dist'+url.pathname,import.meta.url)
        return request.fulfill({body:await readFile(asset),contentType:url.pathname.endsWith('.css')?'text/css':'application/javascript'})
      }
      return request.fulfill({body:html,contentType:'text/html'})
    })
    await page.goto('http://hydration.test'+route.path)
    await page.waitForTimeout(3000)
    assert.equal(await page.locator('h1').count(),1)
    assert.ok((await page.locator('#root').innerText()).includes('合成公开'))
    assert.equal(await page.evaluate(()=>document.documentElement.classList.contains('dark')),false,'saved light theme must eventually apply')
    assert.deepEqual(errors,[],route.path+' must retain SSR while delayed public chunks hydrate')
    await context.close()
  }
}finally{await browser.close()}
console.log('Public SSR hydrates with delayed chunks and fast startup updates without recoverable errors.')
