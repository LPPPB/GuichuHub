import assert from 'node:assert/strict'
import {mkdir,writeFile} from 'node:fs/promises'
import {fileURLToPath} from 'node:url'
import {chromium} from 'playwright-core'
import {PUBLIC_ROUTES} from '../src/routing/publicRoutes.js'

// Headless regression against the isolated synthetic stack; no personal profile.
const base=process.argv[2] || 'http://127.0.0.1:18184'
const directory=process.env.PUBLIC_PAGES_EVIDENCE_DIR || fileURLToPath(new URL('../../.superpowers/sdd/2026-10-18-public-html-routes/browser',import.meta.url))
await mkdir(directory,{recursive:true})
const browser=await chromium.launch({headless:true,channel:'msedge'})
const results=[]
try {
  for(const javaScriptEnabled of [false,true]) {
    const context=await browser.newContext({javaScriptEnabled,viewport:{width:1440,height:1000},timezoneId:'America/Los_Angeles'})
    const page=await context.newPage(),errors=[]
    const requests=[]
    page.on('request',request=>requests.push({url:request.url(),navigation:request.isNavigationRequest()}))
    page.on('pageerror',error=>errors.push(error.message))
    page.on('console',message=>{if(message.type()==='error' && /hydration|Minified React error/.test(message.text()))errors.push(message.text())})
    if(javaScriptEnabled)await page.clock.setFixedTime(new Date('2027-01-01T00:05:00Z'))
    for(const route of PUBLIC_ROUTES) {
      if(javaScriptEnabled && route.tabId==='up-trends') {
        await Promise.all([page.waitForResponse(response=>response.url().includes('/api/up-trends/history')),page.goto(base+route.path)])
      } else await page.goto(base+route.path)
      await page.locator('h1').waitFor()
      assert.ok((await page.locator('#root').innerText()).includes('合成公开'),route.path)
      assert.equal(await page.locator('h1').count(),1)
      if(!javaScriptEnabled)for(const summary of await page.getByRole('definition').all()) {
        assert.ok(await summary.isVisible())
      }
      if(!javaScriptEnabled)for(const summary of await page.locator('dl[aria-label="图表统计摘要"]').all()) {
        const bounds=await summary.evaluate(element=>({bottom:element.getBoundingClientRect().bottom,parent:element.parentElement.getBoundingClientRect().bottom}))
        assert.ok(bounds.bottom<=bounds.parent+1,`${route.path}: text summary overflows reserved chart height`)
      }
      results.push({path:route.path,javaScriptEnabled})
    }
    assert.deepEqual(errors,[], 'browser/hydration errors')
    if(javaScriptEnabled) {
      assert.ok(requests.some(r=>r.url.includes('/api/up-trends/analysis')),'UP browser enhancement must fetch analysis')
      assert.ok(requests.some(r=>r.url.includes('/api/up-trends/history')),'UP browser enhancement must fetch history')
      for(const width of [1920,1440,1280,900,390,320]) {
        await page.setViewportSize({width,height:1000})
        for(const path of ['/rankings/kichu','/up-trends']) {
          await page.goto(base+path)
          await page.locator('h1').waitFor()
          await page.evaluate(()=>document.fonts.ready)
          assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`${width}px ${path} overflow`)
        }
        if([1440,390].includes(width))await page.screenshot({path:`${directory}/${width}.png`,fullPage:true})
      }
      await page.setViewportSize({width:1440,height:1000})
      await page.goto(base+'/rankings/kichu')
      await page.getByRole('link',{name:'热梗',exact:true}).first().click()
      assert.equal(new URL(page.url()).pathname,'/memes')
      await page.goBack()
      assert.equal(new URL(page.url()).pathname,'/rankings/kichu')
      await page.goForward()
      assert.equal(new URL(page.url()).pathname,'/memes')
      await page.reload()
      assert.ok((await page.locator('#root').innerText()).includes('合成公开'))
      const popup=await context.newPage()
      await popup.goto(base+'/bgm')
      assert.ok((await popup.locator('h1').innerText()).includes('BGM'))
      await popup.close()
      await page.setViewportSize({width:390,height:900})
      await page.getByRole('button',{name:'打开导航菜单',exact:true}).click()
      const drawer=page.getByRole('dialog',{name:'站点导航'})
      await drawer.waitFor()
      await drawer.getByRole('link',{name:'梗素材库',exact:true}).click()
      assert.equal(new URL(page.url()).pathname,'/meme-materials')
      assert.equal(await drawer.count(),0)
      await page.getByRole('button',{name:'打开导航菜单',exact:true}).click()
      const theme=drawer.getByRole('button',{name:/切换到.*模式/})
      const previousTheme=await page.evaluate(()=>localStorage.getItem('kb-theme'))
      await theme.click()
      assert.notEqual(await page.evaluate(()=>localStorage.getItem('kb-theme')),previousTheme)
      await drawer.getByRole('button',{name:'关闭导航菜单',exact:true}).click()
      await page.reload()
      assert.notEqual(await page.evaluate(()=>localStorage.getItem('kb-theme')),previousTheme)
      await page.route('**/api/auth/me',route=>route.fulfill({json:{success:true,data:{admin:false,user:{mid:123,name:'隔离测试账号'}}}}))
      await page.reload()
      await page.getByRole('button',{name:'打开导航菜单',exact:true}).click()
      await drawer.getByRole('button',{name:'隔离测试账号',exact:true}).waitFor()
      await drawer.getByRole('button',{name:'我的收藏',exact:true}).click()
      await page.getByRole('heading',{name:/我的收藏/}).waitFor()
      await page.route('**/api/dashboard',route=>route.fulfill({status:503,json:{success:false}}))
      await page.goto(base+'/memes')
      await page.setViewportSize({width:1440,height:1000})
      const beforeNavigation=requests.filter(r=>r.navigation).length
      await page.getByRole('link',{name:'鬼畜榜',exact:true}).first().click()
      await page.getByRole('link',{name:/合成公开.*投稿/,exact:true}).first().waitFor()
      assert.ok(requests.filter(r=>r.navigation).length>beforeNavigation,'unloaded destination must use its cached HTTP document')
      await page.goBack()
      assert.equal(new URL(page.url()).pathname,'/memes')
      await page.goForward()
      await page.getByRole('link',{name:/合成公开.*投稿/,exact:true}).first().waitFor()
    }
    await context.close()
  }
} finally {await browser.close()}
await writeFile(`${directory}/results.json`,JSON.stringify(results,null,2))
console.log(`Verified ${results.length} JS/no-JS route visits, six widths and history navigation.`)
