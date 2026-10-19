import assert from 'node:assert/strict'
import { mkdir, readFile } from 'node:fs/promises'
import { resolve, sep } from 'node:path'
import { chromium } from 'playwright-core'

// Built assets and synthetic responses only. No production requests or credentials.
const root = resolve('dist')
const output = resolve('../runtime/verification/observation-consistency')
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ headless: true,
  ...(process.env.LAYOUT_BROWSER_CHANNEL ? { channel: process.env.LAYOUT_BROWSER_CHANNEL } : {}),
})
try {
  for (const width of [1440, 390]) {
    const page = await browser.newPage({ viewport: { width, height: 1000 } })
    let revision = 1
    let curveRequests = 0
    const errors = []
    page.on('pageerror', error => errors.push(error.message))
    await page.clock.install({ time: new Date('2026-10-18T08:00:00Z') })
    await page.emulateMedia({ colorScheme: 'light' })
    const video = () => ({
      bvid: 'BVconsistency', title: '观测统计一致性验证视频', author: '测试作者',
      views: revision === 1 ? 245764 : 275000, likes: revision === 1 ? 28966 : 33000,
      coins: 994, favorites: 5714, shares: 947, comments: 356, danmaku: 160,
      observed_at: 1792310400+(revision-1)*1800, duration: 90,
    })
    await page.route('**/*', async route => {
      const url = new URL(route.request().url())
      if (url.hostname !== 'observation.test') return route.abort()
      if (url.pathname.startsWith('/api/')) {
        let data = []
        if (url.pathname === '/api/dashboard') data = {
          kichu_rank: [video()], hot_videos: [], material_candidates: [], hot_songs: [],
          hot_memes: [], meme_materials: [], danmaku_words: [], comments_gold: [],
          last_updated: '2026-10-17 03:45:06', is_live: false,
        }
        else if (url.pathname === '/api/status') data = {
          crawling: false, last_updated: '2026-10-17 03:45:06', data_source: 'scheduled',
          observation_revision: [revision, 'baseline'],
        }
        else if (url.pathname.endsWith('/obs-trend')) {
          curveRequests++
          const count = revision === 1 ? 3 : 4
          data = { points: Array.from({ length: count }, (_, i) => ({
            ...video(), ts: 1792306800+i*1800,
            views: i === count-1 ? video().views : 89427+i*30000,
          })) }
        }
        return route.fulfill({ json: { success: true, data } })
      }
      const path = resolve(root, url.pathname === '/' ? 'index.html' : `.${url.pathname}`)
      assert.ok(path.startsWith(root+sep))
      return route.fulfill({ body: await readFile(path), contentType:
        path.endsWith('.js') ? 'application/javascript' : path.endsWith('.css') ? 'text/css' :
          path.endsWith('.svg') ? 'image/svg+xml' : path.endsWith('.png') ? 'image/png' : 'text/html' })
    })
    await page.goto('https://observation.test/')
    const card = page.locator('article').first()
    await card.getByText('24.6万', { exact: true }).waitFor()
    await card.locator('time[aria-label="统计观测时间"]').waitFor()
    assert.equal(await card.getByText('11.8%', { exact: true }).count(), 1)
    await card.getByRole('button', { name: '观测趋势', exact: true }).click()
    await card.getByText('近 48 小时观测（3 个点）', { exact: true }).waitFor()
    await page.screenshot({ path: resolve(output, `${width}-initial.png`) })
    revision = 2
    await page.clock.runFor(16000)
    await card.getByText('27.5万', { exact: true }).waitFor({ timeout: 5000 })
    await card.getByText('近 48 小时观测（4 个点）', { exact: true }).waitFor()
    assert.equal(await card.getByText('12.0%', { exact: true }).count(), 1)
    assert.equal(curveRequests, 2)
    await card.getByRole('button', { name: '互动率', exact: true }).click()
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
    assert.deepEqual(errors, [])
    await page.screenshot({ path: resolve(output, `${width}-updated.png`) })
    await page.close()
    console.log(`${width}px: current counts, ratios, timestamp, polling and expanded curve verified`)
  }
} finally {
  await browser.close()
}
