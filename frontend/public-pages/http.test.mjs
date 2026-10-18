import {test} from 'node:test'
import assert from 'node:assert/strict'
import {createServer} from 'node:http'
import {createPublicPageHandler} from './http.mjs'
import {PUBLIC_ROUTES} from '../src/routing/publicRoutes.js'

async function server(t, pages=new Map(PUBLIC_ROUTES.map(r=>[r.path,{html:`<h1>${r.title}</h1>`,etag:'"abc"'}]))) {
  const instance=createServer(createPublicPageHandler({publisher:{snapshot:()=>pages},buildId:'build-test'}))
  await new Promise(resolve=>instance.listen(0,'127.0.0.1',resolve))
  t.after(()=>new Promise(resolve=>{instance.closeAllConnections();instance.close(resolve)}))
  return `http://127.0.0.1:${instance.address().port}`
}
test('nine exact pages, HEAD, conditional and query requests share cached documents',async t=>{
  const base=await server(t)
  for(const route of PUBLIC_ROUTES) {
    const response=await fetch(base+route.path+'?tracking=1')
    assert.equal(response.status,200)
    assert.equal(response.headers.get('content-type'),'text/html; charset=utf-8')
    assert.equal(response.headers.get('cache-control'),'no-cache')
    assert.equal(response.headers.get('etag'),'"abc"')
    assert.match(await response.text(),/<h1>/)
    assert.equal((await fetch(base+route.path,{method:'HEAD'})).headers.get('etag'),'"abc"')
    assert.equal(await (await fetch(base+route.path,{method:'HEAD'})).text(),'')
    assert.equal((await fetch(base+route.path,{headers:{'If-None-Match':'"other", W/"abc"'}})).status,304)
  }
})
test('canonical redirects, unknown paths and unsupported methods have honest status',async t=>{
  const base=await server(t)
  const redirect=await fetch(base+'/rankings/kichu/?a=1',{redirect:'manual'})
  assert.equal(redirect.status,308)
  assert.equal(redirect.headers.get('location'),'/rankings/kichu?a=1')
  for(const path of ['/unknown','/internal/public-pages','//memes','/rankings%2Fkichu'])assert.equal((await fetch(base+path)).status,404)
  assert.equal((await fetch(base+'/memes',{method:'POST'})).status,405)
  assert.equal(await (await fetch(base+'/__public-pages/build')).text(),'build-test')
})
test('unpublished pages return retryable non-indexable 503',async t=>{
  const base=await server(t,new Map())
  const response=await fetch(base+'/memes')
  assert.equal(response.status,503)
  assert.equal(response.headers.get('retry-after'),'60')
  assert.equal(response.headers.get('x-robots-tag'),'noindex')
})
