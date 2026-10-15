import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { resolve, sep } from 'node:path'
import { JSDOM } from 'jsdom'

const document = new JSDOM(await readFile('dist/index.html', 'utf8')).window.document
assert.equal(document.querySelectorAll('h1').length, 1)
assert.equal(document.querySelector('#root h1').textContent, 'GuichuHub · B站鬼畜创作灵感看板')
assert.ok(document.querySelector('#root main'))
assert.ok(document.querySelector('#root footer'))
assert.ok(document.querySelector('script[type="module"][src^="/assets/"]'))
assert.match(document.title, /GuichuHub.*鬼畜/)
assert.ok(document.querySelector('meta[name="description"]').content.length > 30)
assert.equal(document.querySelector('link[rel="canonical"]').href, 'https://guichuhub.cn/')
assert.equal(JSON.parse(document.querySelector('script[type="application/ld+json"]').textContent)['@type'], 'WebSite')
assert.ok(document.querySelector('meta[name="msvalidate.01"]'))
assert.ok(document.querySelector('meta[name="baidu-site-verification"]'))
for (const icon of document.querySelectorAll('link[rel="icon"],link[rel="apple-touch-icon"]')) {
  const data = await readFile(`dist${icon.getAttribute('href')}`)
  assert.ok(data.length > 100)
}
const robots = await readFile('dist/robots.txt', 'utf8')
assert.match(robots, /Allow: \/\s/)
assert.match(robots, /Disallow: \/api\//)
assert.match(robots, /Sitemap: https:\/\/guichuhub.cn\/sitemap.xml/)
const sitemap = new JSDOM(await readFile('dist/sitemap.xml', 'utf8'), { contentType: 'text/xml' }).window.document
const urls = [...sitemap.querySelectorAll('loc')].map(node => node.textContent)
assert.ok(urls.includes('https://guichuhub.cn/'))
assert.equal(new Set(urls).size, urls.length)
for (const href of urls) {
  const url = new URL(href)
  assert.equal(url.origin, 'https://guichuhub.cn')
  assert.equal(url.search + url.hash, '')
  const path = resolve('dist', `.${decodeURIComponent(url.pathname)}`, url.pathname.endsWith('/') ? 'index.html' : '')
  assert.ok(path.startsWith(resolve('dist') + sep))
  const page = new JSDOM(await readFile(path, 'utf8')).window.document
  assert.equal(page.querySelector('link[rel="canonical"]')?.href, href)
}
console.log('Built HTML is crawlable without JavaScript: one H1, site metadata, local icons, robots, sitemap, and WebSite JSON-LD.')
