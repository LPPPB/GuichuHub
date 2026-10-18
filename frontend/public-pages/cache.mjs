import * as fs from 'node:fs/promises'
import { join } from 'node:path'
import { randomUUID, createHash } from 'node:crypto'
import { PUBLIC_ROUTES } from '../src/routing/publicRoutes.js'

const paths = new Set(PUBLIC_ROUTES.map(route=>route.path))
const sha = text => createHash('sha256').update(text).digest('hex')
export function createDiskCache({directory,buildId,io=fs}) {
  return {
    async load() {
      try {
        const generation=(await io.readFile(join(directory,'CURRENT'),'utf8')).trim()
        if (!/^[a-f0-9-]{36}$/.test(generation)) return new Map()
        const base=join(directory,generation)
        const manifest=JSON.parse(await io.readFile(join(base,'manifest.json'),'utf8'))
        if (manifest.schema_version!==1 || (await io.stat(join(base,'pages.json'))).size>64*1024*1024) return new Map()
        const payload=await io.readFile(join(base,'pages.json'),'utf8')
        if (sha(payload)!==manifest.sha256) return new Map()
        const rows=JSON.parse(payload)
        if (!Array.isArray(rows) || rows.length>9 || rows.some(([path,value])=>!paths.has(path)||typeof value.html!=='string'||typeof value.etag!=='string')) return new Map()
        return new Map(rows)
      } catch { return new Map() }
    },
    async commitBatch(batch) {
      if (!(batch instanceof Map) || batch.size>9 || [...batch.keys()].some(path=>!paths.has(path))) throw Error('Invalid public cache paths')
      const payload=JSON.stringify([...batch])
      if (Buffer.byteLength(payload)>64*1024*1024) throw Error('Public cache too large')
      const generation=randomUUID()
      const base=join(directory,generation)
      await io.mkdir(base,{recursive:true})
      await io.writeFile(join(base,'pages.json'),payload,{flag:'wx'})
      await io.writeFile(join(base,'manifest.json'),JSON.stringify({schema_version:1,build_id:buildId,sha256:sha(payload)}),{flag:'wx'})
      const pointer=join(directory,`CURRENT.${generation}.tmp`)
      await io.writeFile(pointer,generation,{flag:'wx'})
      await io.rename(pointer,join(directory,'CURRENT'))
    },
  }
}
