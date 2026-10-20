import {readFile} from 'node:fs/promises'
import {createServer} from 'node:http'
import {renderPublicPage} from '../dist-server/ssr.mjs'
import {createDiskCache} from './cache.mjs'
import {createPublisher} from './publisher.mjs'
import {createPublicPageHandler} from './http.mjs'

const buildId=(await readFile(new URL('../dist-server/build-id.txt',import.meta.url),'utf8')).trim()
const template=await readFile(new URL('../dist-server/template.html',import.meta.url),'utf8')
const publisher=createPublisher({
  buildId,cache:createDiskCache({directory:process.env.PUBLIC_PAGES_CACHE_DIR || '/cache',buildId}),
  renderPage:args=>renderPublicPage({...args,template}),
  async fetchSections({signal}) {
    const response=await fetch('http://api:5000/internal/public-pages',{signal,redirect:'error'})
    if(!response.ok || !response.headers.get('content-type')?.includes('application/json'))throw Error('Public export unavailable')
    const chunks=[];let size=0
    for await(const chunk of response.body) {
      size+=chunk.length
      if(size>2*1024*1024)throw Error('Public export too large')
      chunks.push(chunk)
    }
    return JSON.parse(Buffer.concat(chunks).toString('utf8'))
  },
})
const server=createServer(createPublicPageHandler({publisher,buildId}))
server.requestTimeout=15_000
server.listen(8081,'0.0.0.0')
let stopped=false,timer
async function poll() {
  try {
    const result=await publisher.refresh()
    console.log(JSON.stringify({event:'public-pages',changed:result.changedPaths.length,failures:result.failures}))
  } catch { console.error('Public page refresh failed') }
  if(!stopped)timer=setTimeout(poll,60_000)
}
poll()
for(const signal of ['SIGINT','SIGTERM'])process.once(signal,()=>{
  stopped=true;clearTimeout(timer)
  server.close(()=>process.exit(0))
  setTimeout(()=>process.exit(0),15_000).unref()
})
