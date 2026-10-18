import { readFile, writeFile } from 'node:fs/promises'
import { createElement } from 'react'
import { renderToString } from 'react-dom/server'
import { createServer } from 'vite'

// Render the same public loading shell as the browser. Effects never run here:
// no API requests, user identity, credentials, or volatile ranking snapshots.
const server = await createServer({ server: { middlewareMode: true }, appType: 'custom' })
try {
  const { default: App } = await server.ssrLoadModule('/src/App.jsx')
  const shell = renderToString(createElement(App))
  if (!shell.includes('<h1>GuichuHub')) throw new Error('Home heading missing from prerender')
  const html = await readFile('dist/index.html', 'utf8')
  const placeholder = '<div id="root"></div>'
  if (!html.includes(placeholder)) throw new Error('Expected one empty root in the Vite output')
  await writeFile('dist/index.html', html.replace(placeholder, () => `<div id="root">${shell}</div>`))
  console.log('Prerendered public home shell and H1; dynamic data stays client-rendered.')
} finally {
  await server.close()
}
