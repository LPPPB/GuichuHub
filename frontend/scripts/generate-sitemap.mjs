import { readdir, readFile, writeFile } from 'node:fs/promises'
import { join, relative, resolve, sep } from 'node:path'
import { JSDOM } from 'jsdom'

// Discover built pages, not React tabs or guessed routes. No requests to the
// production site, API, Git history, user identity, or runtime data are needed.
const output = resolve(process.argv[2] || 'dist')

async function inspectPage(path) {
  const dom = new JSDOM(await readFile(path, 'utf8'))
  try {
    const document = dom.window.document
    const links = document.querySelectorAll('link[rel="canonical"]')
    let canonical
    try { if (links.length === 1) canonical = new URL(links[0].getAttribute('href')) } catch { /* Not a usable absolute canonical. */ }
    const noindex = [...document.querySelectorAll('meta[name]')].some(meta =>
      /^(robots|googlebot|bingbot)$/i.test(meta.name) && /(?:^|[\s,])(noindex|none)(?:$|[\s,])/i.test(meta.content))
    const redirect = [...document.querySelectorAll('meta[http-equiv]')].some(meta =>
      meta.httpEquiv.toLowerCase() === 'refresh')
    return { canonical, noindex, redirect }
  } finally {
    dom.window.close()
  }
}

const home = await inspectPage(join(output, 'index.html'))
const canonical = home.canonical
if (!canonical || canonical.protocol !== 'https:' || canonical.pathname !== '/' ||
    canonical.search || canonical.hash || canonical.username || canonical.password || home.noindex || home.redirect) {
  throw new Error('Invalid sitemap home: expected one indexable HTTPS root canonical without query, fragment, or credentials')
}

async function discover(directory) {
  const pages = []
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name)
    if (entry.isDirectory()) pages.push(...await discover(path))
    else if (entry.isFile() && entry.name.endsWith('.html')) pages.push(path)
  }
  return pages // Symlinks are not followed outside the built output.
}

const urls = []
// Encode literal #, ?, %, spaces and Unicode in filesystem names, while
// preserving RFC 3986 path-segment delimiters such as & and :.
const encodeSegment = segment => encodeURIComponent(segment).replace(
  /%(?:24|26|2B|2C|3B|3D|3A|40)/gi, escaped => decodeURIComponent(escaped))
for (const file of await discover(output)) {
  const page = file === join(output, 'index.html') ? home : await inspectPage(file)
  const path = '/' + relative(output, file).split(sep).map(encodeSegment).join('/').replace(/(^|\/)index\.html$/, '$1')
  const expected = new URL(path, canonical.origin).href
  if (!page.noindex && !page.redirect && page.canonical?.href === expected) urls.push(expected)
}
if (!urls.includes(canonical.href)) throw new Error('Invalid sitemap home: homepage was not discovered')
const escapeXml = value => value.replace(/[&<>"']/g, character => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&apos;',
})[character])
const entries = [...new Set(urls)].sort().map(url => `  <url>\n    <loc>${escapeXml(url)}</loc>\n  </url>`)
// No lastmod is emitted without a reliable content modification timestamp.
const xml = `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${entries.join('\n')}\n</urlset>\n`
await writeFile(join(output, 'sitemap.xml'), xml)
console.log(`Generated sitemap.xml from ${entries.length} real, indexable canonical HTML page(s).`)
