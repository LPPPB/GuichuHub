import assert from 'node:assert/strict'
import {setTimeout as delay} from 'node:timers/promises'
const base=process.argv[2] || 'http://127.0.0.1:18184'
const page=async path=>{const response=await fetch(base+path);return {html:await response.text(),etag:response.headers.get('etag')}}
const before=await page('/memes'),upBefore=await page('/up-trends')
await fetch(base+'/__test/change')
const changedAt=Date.now()
let after
do {
  after=await page('/memes')
  if(after.etag!==before.etag)break
  await delay(2000)
} while(Date.now()-changedAt<120_000)
assert.notEqual(after.etag,before.etag)
assert.match(after.html,/合成公开v2热梗/)
assert.equal((await page('/up-trends')).etag,upBefore.etag)
console.log(`Persisted dashboard change published after ${Date.now()-changedAt}ms; UP unchanged.`)
await fetch(base+'/__test/fail')
await fetch(base+'/__test/up-change')
const upChangedAt=Date.now()
let upAfter
do {
  upAfter=await page('/up-trends')
  if(upAfter.etag!==upBefore.etag)break
  await delay(2000)
} while(Date.now()-upChangedAt<120_000)
assert.notEqual(upAfter.etag,upBefore.etag)
assert.match(upAfter.html,/合成公开v2作者/)
assert.equal((await page('/memes')).etag,after.etag)
console.log(`Independent UP change published after ${Date.now()-upChangedAt}ms; failed dashboard retained.`)
await fetch(base+'/__test/up-fail')
console.log('Both sources now unavailable. Restart only the isolated publisher, then compare retained ETags.')
console.log(JSON.stringify({memes:after.etag,up:upAfter.etag}))
