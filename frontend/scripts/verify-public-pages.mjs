import assert from 'node:assert/strict'
import {JSDOM} from 'jsdom'
import {PUBLIC_ROUTES} from '../src/routing/publicRoutes.js'

const base=process.argv[2] || 'http://127.0.0.1:18184'
const verified=[]
for(const route of PUBLIC_ROUTES) {
  const response=await fetch(base+route.path)
  assert.equal(response.status,200,route.path)
  assert.equal(response.headers.get('content-type'),'text/html; charset=utf-8')
  assert.equal(response.headers.get('cache-control'),'no-cache')
  const html=await response.text(),doc=new JSDOM(html).window.document
  assert.equal(doc.querySelectorAll('h1').length,1,route.path)
  assert.ok(doc.querySelector('#root').textContent.includes('合成公开'),route.path+' lacks visible fixture')
  assert.equal(doc.querySelector('link[rel=canonical]').href,'https://guichuhub.cn'+route.path)
  assert.equal(doc.querySelectorAll('a[href="/rankings/kichu"]').length>0,true)
  const bootstrap=JSON.parse(doc.querySelector('#public-page-bootstrap').textContent)
  assert.equal(bootstrap.tab_id,route.tabId)
  assert.equal(await (await fetch(base+route.path,{method:'HEAD'})).text(),'')
  assert.equal((await fetch(base+route.path,{headers:{'If-None-Match':response.headers.get('etag')}})).status,304)
  for(const script of doc.querySelectorAll('script[src]'))assert.equal((await fetch(new URL(script.src,base))).status,200)
  verified.push(route.path)
}
for(const path of ['/unknown','/internal/public-pages','/__public-pages/build','/rankings%2Fkichu','//memes','/index.html'])
  assert.equal((await fetch(base+path)).status,404,path)
const redirect=await fetch(base+'/rankings/kichu/?a=1',{redirect:'manual'})
assert.equal(redirect.status,308)
assert.ok(redirect.headers.get('location').endsWith('/rankings/kichu?a=1'))
const icon=await fetch(base+'/favicon.ico')
assert.equal(icon.status,200)
assert.match(icon.headers.get('content-type'),/image\/(x-icon|vnd.microsoft.icon)/)
assert.match(icon.headers.get('cache-control'),/max-age=3600/)
console.log(JSON.stringify({verifiedPublicPages:verified,verifiedAt:new Date().toISOString()},null,2))
