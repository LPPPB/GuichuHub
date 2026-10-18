// @vitest-environment node
import { execFileSync } from 'node:child_process'
import { mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { basename, dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { JSDOM } from 'jsdom'
import { afterEach, expect, it } from 'vitest'

const script = fileURLToPath(new URL('./scripts/generate-sitemap.mjs', import.meta.url))
const folders = []
async function fixture(files) {
  const root = await mkdtemp(join(tmpdir(), 'guichuhub-sitemap-'))
  folders.push(root)
  for (const [path, content] of Object.entries(files)) {
    await mkdir(dirname(join(root, path)), { recursive: true })
    await writeFile(join(root, path), content)
  }
  return root
}
const page = (canonical, extra = '') => `<!doctype html><html><head><link rel="canonical" href="${canonical}">${extra}</head><body><h1>公开内容</h1></body></html>`
const generate = root => execFileSync(process.execPath, [script, root], { encoding: 'utf8', stdio: 'pipe' })
const parse = xml => new JSDOM(xml, { contentType: 'text/xml' }).window.document
afterEach(async () => {
  for (const root of folders.splice(0)) {
    if (dirname(resolve(root)) !== resolve(tmpdir()) || !basename(root).startsWith('guichuhub-sitemap-')) {
      throw new Error('Refusing cleanup outside the generated sitemap test directories')
    }
    await rm(root, { recursive: true, force: true })
  }
})

it('discovers real canonical HTML pages and excludes noindex, redirects, aliases and verification files', async () => {
  const root = await fixture({
    'index.html': page('https://guichuhub.cn/'),
    'rankings/index.html': page('https://guichuhub.cn/rankings/'),
    'notes#1/index.html': page('https://guichuhub.cn/notes%231/'),
    'percent%20literal/index.html': page('https://guichuhub.cn/percent%2520literal/'),
    'wrong#hash/index.html': page('https://guichuhub.cn/wrong#hash/'),
    'research&notes/index.html': page('https://guichuhub.cn/research&amp;notes/'),
    'admin/index.html': page('https://guichuhub.cn/admin/', '<meta name="robots" content="noindex, nofollow">'),
    'draft/index.html': page('https://guichuhub.cn/draft/', '<meta name="robots" content="none">'),
    'alias/index.html': page('https://guichuhub.cn/'),
    'old/index.html': page('https://guichuhub.cn/old/', '<meta http-equiv="refresh" content="0;url=/">'),
    'outside/index.html': page('https://example.com/outside/'),
    'verification.html': 'verification-token',
  })
  generate(root)
  const xml = await readFile(join(root, 'sitemap.xml'), 'utf8')
  const document = parse(xml)
  expect([...document.querySelectorAll('loc')].map(node => node.textContent)).toEqual([
    'https://guichuhub.cn/', 'https://guichuhub.cn/notes%231/', 'https://guichuhub.cn/percent%2520literal/',
    'https://guichuhub.cn/rankings/', 'https://guichuhub.cn/research&notes/',
  ])
  expect(xml).toContain('research&amp;notes')
  expect(document.documentElement.namespaceURI).toBe('http://www.sitemaps.org/schemas/sitemap/0.9')
})

it('produces repeatable output without inventing modification dates', async () => {
  const root = await fixture({ 'index.html': page('https://guichuhub.cn/') })
  generate(root)
  const before = await readFile(join(root, 'sitemap.xml'), 'utf8')
  generate(root)
  expect(await readFile(join(root, 'sitemap.xml'), 'utf8')).toBe(before)
  expect(parse(before).querySelector('lastmod')).toBeNull()
})

it.each([
  ['missing canonical', '<html><head></head></html>'],
  ['insecure origin', page('http://guichuhub.cn/')],
  ['home canonical has a query', page('https://guichuhub.cn/?tab=home')],
  ['noindex home', page('https://guichuhub.cn/', '<meta name="robots" content="noindex">')],
])('fails the build for %s and preserves the previous file', async (_reason, html) => {
  const root = await fixture({ 'index.html': html, 'sitemap.xml': 'previous-output' })
  expect(() => generate(root)).toThrow(/Invalid sitemap home:/)
  expect(await readFile(join(root, 'sitemap.xml'), 'utf8')).toBe('previous-output')
})
