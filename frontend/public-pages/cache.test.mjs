import test from 'node:test'
import assert from 'node:assert/strict'
import * as fs from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { createDiskCache } from './cache.mjs'
const page={html:'<html>success</html>',etag:'"one"',bootstrap:{build_id:'build1'}}
test('recovers only the committed generation after restart and ignores partial files',async t=>{
  const directory=await fs.mkdtemp(join(tmpdir(),'public-cache-'))
  t.after(()=>fs.rm(directory,{recursive:true,force:true}))
  const cache=createDiskCache({directory,buildId:'build1'})
  assert.equal((await cache.load()).size,0)
  await cache.commitBatch(new Map([['/',page]]))
  await fs.writeFile(join(directory,'uncommitted.tmp'),'broken')
  assert.deepEqual((await createDiskCache({directory,buildId:'build1'}).load()).get('/'),page)
})
test('failed pointer rename preserves previous committed generation',async t=>{
  const directory=await fs.mkdtemp(join(tmpdir(),'public-cache-'))
  t.after(()=>fs.rm(directory,{recursive:true,force:true}))
  await createDiskCache({directory,buildId:'build1'}).commitBatch(new Map([['/',page]]))
  const broken=createDiskCache({directory,buildId:'build1',io:{...fs,rename:async()=>{throw Error('disk unavailable')}}})
  await assert.rejects(broken.commitBatch(new Map([['/',{...page,html:'broken'}]])))
  assert.equal((await createDiskCache({directory,buildId:'build1'}).load()).get('/').html,page.html)
})
test('rejects path traversal and corrupt manifest',async t=>{
  const directory=await fs.mkdtemp(join(tmpdir(),'public-cache-'))
  t.after(()=>fs.rm(directory,{recursive:true,force:true}))
  await fs.writeFile(join(directory,'CURRENT'),'../../private')
  const cache=createDiskCache({directory,buildId:'build1'})
  assert.equal((await cache.load()).size,0)
  await assert.rejects(cache.commitBatch(new Map([['/../../secret',page]])))
  await cache.commitBatch(new Map([['/',page]]))
  const generation=(await fs.readFile(join(directory,'CURRENT'),'utf8')).trim()
  await fs.writeFile(join(directory,generation,'pages.json'),'[]')
  assert.equal((await cache.load()).size,0)
})

test('bounds owned generations to current and previous without touching unrelated files',async t=>{
  const directory=await fs.mkdtemp(join(tmpdir(),'public-cache-'))
  t.after(()=>fs.rm(directory,{recursive:true,force:true}))
  const unrelated='00000000-0000-0000-0000-000000000000'
  await fs.mkdir(join(directory,unrelated))
  await fs.writeFile(join(directory,unrelated,'private.txt'),'keep')
  const cache=createDiskCache({directory,buildId:'build1'}),generations=[]
  for(let index=0;index<6;index++){
    await cache.commitBatch(new Map([['/',{...page,html:'version '+index}]]))
    generations.push((await fs.readFile(join(directory,'CURRENT'),'utf8')).trim())
  }
  const directories=(await fs.readdir(directory,{withFileTypes:true})).filter(entry=>entry.isDirectory()).map(entry=>entry.name)
  assert.deepEqual(directories.sort(),[unrelated,...generations.slice(-2)].sort())
  assert.equal((await cache.load()).get('/').html,'version 5')
  const previous=JSON.parse(await fs.readFile(join(directory,generations.at(-2),'pages.json'),'utf8'))
  assert.equal(previous[0][1].html,'version 4')
  assert.equal(await fs.readFile(join(directory,unrelated,'private.txt'),'utf8'),'keep')
})

test('cleanup failure does not reject or undo a successfully committed page',async t=>{
  const directory=await fs.mkdtemp(join(tmpdir(),'public-cache-'))
  t.after(()=>fs.rm(directory,{recursive:true,force:true}))
  const cache=createDiskCache({directory,buildId:'build1'})
  await cache.commitBatch(new Map([['/',page]]))
  await cache.commitBatch(new Map([['/',{...page,html:'second'}]]))
  const warning=t.mock.method(console,'warn',()=>{})
  const broken=createDiskCache({directory,buildId:'build1',io:{...fs,rm:async()=>{throw Error('cleanup unavailable')}}})
  await broken.commitBatch(new Map([['/',{...page,html:'third'}]]))
  assert.equal((await cache.load()).get('/').html,'third')
  assert.equal(warning.mock.callCount(),1)
})
