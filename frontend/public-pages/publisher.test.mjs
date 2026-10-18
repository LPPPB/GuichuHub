import test from 'node:test'
import assert from 'node:assert/strict'
import { createPublisher } from './publisher.mjs'

const section = (v, field='kichu_rank') => ({status:'ready',content_version:v,source_updated_at:null,data:{[field]:[{title:v,bvid:'BV1HYp16oE8v'}]}})
function harness() {
  let input={schema_version:1,sections:{'kichu-rank':section('one')}}
  let calls=0, failRender=false, failDisk=false, saved=new Map()
  const publisher=createPublisher({buildId:'build1',clock:()=>1000,
    fetchSections:async()=>structuredClone(input),
    renderPage:async ({route,bootstrap})=>{calls++;if(failRender && route.tabId==='memes')throw Error('render');return JSON.stringify(bootstrap)},
    cache:{load:async()=>saved,commitBatch:async batch=>{if(failDisk)throw Error('disk');saved=new Map(batch)}},
  })
  return {publisher,setInput:v=>{input=v},calls:()=>calls,failRender:()=>{failRender=true},failDisk:()=>{failDisk=true}}
}
test('publishes changed content and leaves timestamps and ETag unchanged for equal versions', async()=>{
  const h=harness();await h.publisher.refresh()
  const before=h.publisher.snapshot().get('/rankings/kichu');const calls=h.calls()
  assert.ok(before.html.includes('one'))
  assert.deepEqual((await h.publisher.refresh()).changedPaths,[])
  assert.equal(h.calls(),calls)
  assert.equal(h.publisher.snapshot().get('/rankings/kichu').etag,before.etag)
  assert.equal(before.bootstrap.confirmed_at['kichu-rank'],1000)
})
test('keeps failed source and home summary while independently updating another source', async()=>{
  const h=harness();await h.publisher.refresh()
  const before=h.publisher.snapshot().get('/rankings/kichu')
  h.setInput({schema_version:1,sections:{'kichu-rank':{status:'unavailable',data:{}},memes:section('new meme','hot_memes')}})
  await h.publisher.refresh()
  assert.equal(h.publisher.snapshot().get('/rankings/kichu').etag,before.etag)
  assert.ok(h.publisher.snapshot().get('/').html.includes('one'))
  assert.ok(h.publisher.snapshot().get('/memes').html.includes('new meme'))
})
test('failed candidate render or disk commit never replaces a successful batch', async()=>{
  const h=harness();await h.publisher.refresh()
  const home=h.publisher.snapshot().get('/').etag
  h.setInput({schema_version:1,sections:{memes:section('bad','hot_memes')}});h.failRender()
  assert.ok((await h.publisher.refresh()).failures.length)
  assert.equal(h.publisher.snapshot().get('/').etag,home)
  assert.equal(h.publisher.snapshot().has('/memes'),false)
  h.setInput({schema_version:1,sections:{'kichu-rank':section('two')}});h.failDisk()
  await h.publisher.refresh()
  assert.equal(h.publisher.snapshot().get('/').etag,home)
})
test('coalesces overlapping refreshes and retains successful data after fetch failure', async()=>{
  let finish,requests=0
  const publisher=createPublisher({buildId:'build1',clock:()=>1000,
    fetchSections:()=>{requests++;return new Promise(resolve=>{finish=resolve})},renderPage:async()=>'<html>one</html>',
    cache:{load:async()=>new Map(),commitBatch:async()=>{}},
  })
  const a=publisher.refresh(),b=publisher.refresh()
  await new Promise(resolve=>setImmediate(resolve))
  finish({schema_version:1,sections:{'kichu-rank':section('one')}})
  await Promise.all([a,b]);assert.equal(requests,1)
})
test('publishes an explicit empty result and refreshes UP independently', async()=>{
  const h=harness();await h.publisher.refresh()
  h.setInput({schema_version:1,sections:{'kichu-rank':{status:'empty',content_version:'empty',source_updated_at:null,data:{kichu_rank:[]}},'up-trends':section('UP','up_analysis')}})
  await h.publisher.refresh()
  assert.equal(h.publisher.snapshot().get('/rankings/kichu').bootstrap.sections['kichu-rank'].status,'empty')
  assert.ok(h.publisher.snapshot().get('/up-trends').html.includes('UP'))
})
test('a fetch timeout aborts and returns without replacing the committed page',async()=>{
  const saved=new Map(), row=section('last good')
  let offline=false,aborted=false
  const publisher=createPublisher({buildId:'build1',timeoutMs:15,
    fetchSections:async({signal})=>{
      if(!offline)return {schema_version:1,sections:{'kichu-rank':row}}
      signal.addEventListener('abort',()=>{aborted=true});return new Promise(()=>{})
    },renderPage:async()=>'<html>last good</html>',cache:{load:async()=>saved,commitBatch:async()=>{}},
  })
  await publisher.refresh();const before=publisher.snapshot().get('/').etag
  offline=true
  assert.ok((await publisher.refresh()).failures.includes('fetch'))
  assert.equal(aborted,true)
  assert.equal(publisher.snapshot().get('/').etag,before)
})
test('a new build regenerates old cached content before exposing documents',async()=>{
  const h=harness();await h.publisher.refresh();const old=h.publisher.snapshot()
  const publisher=createPublisher({buildId:'build2',fetchSections:async()=>{throw Error('offline')},
    renderPage:async({bootstrap})=>`new assets ${bootstrap.build_id}`,cache:{load:async()=>old,commitBatch:async()=>{}},
  })
  assert.equal(publisher.snapshot().size,0)
  await publisher.refresh()
  assert.equal(publisher.snapshot().get('/rankings/kichu').html,'new assets build2')
  assert.equal(publisher.snapshot().get('/rankings/kichu').bootstrap.confirmed_at['kichu-rank'],1000)
})
