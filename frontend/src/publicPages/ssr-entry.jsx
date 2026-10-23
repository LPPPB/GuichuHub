import React from 'react'
import { renderToPipeableStream } from 'react-dom/server'
import { PassThrough } from 'node:stream'
import App from '../App'
import { initialProps, serializeBootstrap, validateBootstrap } from './contract'
import { routeForTab, PUBLIC_ROUTES } from '../routing/publicRoutes'
export { PUBLIC_ROUTES }

const escape = text => text.replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))
function renderTree(props) {
  return new Promise((resolve, reject) => {
    const output = new PassThrough()
    const chunks = []
    let size = 0
    const timer = setTimeout(() => { stream.abort(); reject(new Error('Public render timeout')) }, 10_000)
    output.on('data', chunk => {
      size += chunk.length
      if (size > 8 * 1024 * 1024) { stream.abort(); reject(new Error('Public render too large')) }
      else chunks.push(chunk)
    })
    output.on('end', () => { clearTimeout(timer); resolve(Buffer.concat(chunks).toString('utf8')) })
    output.on('error', error => { clearTimeout(timer); reject(error) })
    const stream = renderToPipeableStream(<React.StrictMode><App {...props} /></React.StrictMode>, {
      onAllReady() { stream.pipe(output) },
      onError(error) { clearTimeout(timer); stream.abort(); reject(error) },
    })
  })
}
export async function renderPublicPage({route, bootstrap, template}) {
  const known = routeForTab(route.tabId)
  if (!known || known.path !== route.path || bootstrap.tab_id !== route.tabId || !validateBootstrap(bootstrap)) throw new Error('Invalid public page')
  if (!template.includes('<div id="root"></div>')) throw new Error('Missing empty public root template')
  const body = await renderTree(initialProps(bootstrap))
  const title = known.tabId === 'dashboard' ? known.title : `${known.title} · GuichuHub`
  return template.replace(/<title>[\s\S]*?<\/title>/, () => `<title>${escape(title)}</title>`)
    .replace('</head>', () => `<meta name="robots" content="${known.noindex ? 'noindex' : 'index'}, follow"></head>`)
    .replace(/<link\s+rel="canonical"[^>]*>/, () => `<link rel="canonical" href="https://guichuhub.cn${known.path}">`)
    .replace('<div id="root"></div>', () => `<div id="root">${body}</div><script id="public-page-bootstrap" type="application/json">${serializeBootstrap(bootstrap)}</script>`)
}
