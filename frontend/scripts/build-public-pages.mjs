import { build } from 'vite'
import react from '@vitejs/plugin-react'
import { readFile, writeFile, readdir } from 'node:fs/promises'
import { createHash } from 'node:crypto'

await build({configFile:false, plugins:[react()], build:{
  ssr:'src/publicPages/ssr-entry.jsx', outDir:'dist-server', emptyOutDir:true,
  rollupOptions:{output:{entryFileNames:'ssr.mjs'}},
}})
await writeFile('dist-server/template.html', await readFile('dist/index.html'))
const digest = createHash('sha256')
async function hashTree(directory) {
  for (const entry of (await readdir(directory,{withFileTypes:true})).sort((a,b) => a.name.localeCompare(b.name))) {
    const path = `${directory}/${entry.name}`
    if (entry.isDirectory()) await hashTree(path)
    else { digest.update(path); digest.update(await readFile(path)) }
  }
}
await hashTree('dist/assets')
await hashTree('dist-server')
const buildId = digest.digest('hex')
await writeFile('dist/build-id.txt', buildId)
await writeFile('dist-server/build-id.txt', buildId)
console.log(`Public page build ${buildId.slice(0,12)}`)
