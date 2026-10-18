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
