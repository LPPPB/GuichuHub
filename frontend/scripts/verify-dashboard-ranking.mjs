import assert from 'node:assert/strict'
import { mkdir, readFile } from 'node:fs/promises'
import { resolve, sep } from 'node:path'
import { chromium } from 'playwright-core'

// Exercise the built app against synthetic data without accessing a backend.
const root = resolve('dist')
const output = process.env.LAYOUT_SCREENSHOT_DIR
const videos = Array.from({ length: 7 }, (_, i) => ({
  bvid: `BVsummary${i + 1}`,
  title: `${i + 1} · 烧心大赛！【AI全民制作人】长标题在桌面与手机端都应该保持清楚易读`,
  author: '很长的 UP 主名称用于检查窄屏信息布局',
  cover: 'https://layout.test/cover.svg', views: 4197000 - i * 300000, likes: 180000,
  shares: 21000, comments: 80, danmaku: 120, duration: 60,
  potential_score: 91.9, potential_reason: '互动爆款', trend_label: '爆发期',
  pub_date: 1791979560, tname: '鬼畜剧场',
  description: '一觉醒来，朝夕相伴的 AI 软件竟然变成真人睡在我身边，完整保留上半区的视频简介和核心指标。',
  online_observation: { count: 889, display: '889', precision: 'exact', status: 'available', observed_at: 1792247400 },
}))
const browser = await chromium.launch({
  headless: true,
  ...(process.env.LAYOUT_BROWSER_CHANNEL ? { channel: process.env.LAYOUT_BROWSER_CHANNEL } : {}),
  ...(process.env.LAYOUT_BROWSER_PATH ? { executablePath: process.env.LAYOUT_BROWSER_PATH } : {}),
})
try {
  if (output) await mkdir(output, { recursive: true })
  for (const colorScheme of ['light', 'dark']) {
    for (const width of [1440, 1280, 900, 390, 320]) {
      const page = await browser.newPage({ viewport: { width, height: 1000 }, colorScheme })
      const errors = []
      page.on('pageerror', error => errors.push(error.message))
      await page.route('**/*', async route => {
        const url = new URL(route.request().url())
        if (url.hostname !== 'layout.test') return route.abort()
        if (url.pathname.startsWith('/api/')) {
          const data = url.pathname === '/api/dashboard' ? {
            kichu_rank: videos, hot_videos: [], hot_memes: [], hot_songs: [],
            material_candidates: [], meme_materials: [], danmaku_words: [], comments_gold: [],
          } : url.pathname === '/api/auth/me' ? null : []
          return route.fulfill({ json: { success: true, data } })
        }
        if (url.pathname === '/cover.svg') return route.fulfill({ contentType: 'image/svg+xml', body:
          '<svg xmlns="http://www.w3.org/2000/svg" width="176" height="100"><rect width="176" height="100" fill="#ecc4c5"/><circle cx="65" cy="48" r="28" fill="#50729b"/><path d="M115 30L145 50L115 70Z" fill="#fff"/></svg>' })
        const path = resolve(root, url.pathname === '/' ? 'index.html' : `.${url.pathname}`)
        assert.ok(path.startsWith(root + sep))
        return route.fulfill({ body: await readFile(path), contentType: path.endsWith('.js') ?
          'application/javascript' : path.endsWith('.css') ? 'text/css' : 'text/html' })
      })
      await page.goto('https://layout.test/')
      const summary = page.getByRole('region', { name: '鬼畜区排行榜', exact: true })
      await summary.waitFor()
      await page.evaluate(async () => {
        await document.fonts.ready
        await Promise.all(document.getAnimations().filter(animation =>
          Number.isFinite(animation.effect.getComputedTiming().iterations)
        ).map(animation => animation.finished.catch(() => {})))
      })
      assert.equal(await summary.getByRole('listitem').count(), 5)
      const headingColors = await summary.locator('.dashboard-ranking-heading').evaluate(el => ({
        icon: getComputedStyle(el.querySelector('svg')).color,
        title: getComputedStyle(el.querySelector('h2')).color,
        theme: `rgb(${getComputedStyle(el).getPropertyValue('--haze-50').trim().split(/[,\s]+/).join(', ')})`,
      }))
      assert.equal(headingColors.icon, headingColors.theme)
      assert.equal(headingColors.icon, headingColors.title)
      assert.equal(await summary.getByRole('button', { name: '观测趋势', exact: true }).count(), 5)
      assert.equal(await summary.getByRole('button', { name: '收藏', exact: true }).count(), 0)
      assert.equal(await summary.getByRole('button', { name: 'AI 总结' }).count(), 0)
      assert.equal(await summary.locator('.video-card-footer').count(), 0)
      assert.equal(await summary.getByRole('link', { name: videos[5].title, exact: true }).count(), 0)
      const layout = await summary.evaluate(el => ({
        width: el.getBoundingClientRect().width,
        height: el.getBoundingClientRect().height,
        overflow: document.documentElement.scrollWidth > innerWidth,
        rows: [...el.querySelectorAll('li')].map(row => row.getBoundingClientRect().height),
        truncated: [...el.querySelectorAll('h4 a')].some(title => title.scrollWidth > title.clientWidth),
      }))
      assert.equal(layout.overflow, false, `${width}px ${colorScheme}: page overflow`)
      assert.equal(layout.truncated, false, `${width}px ${colorScheme}: title overflow`)
      const card = summary.locator('article').first()
      const positions = await card.evaluate(el => {
        const rect = selector => {
          const box = el.querySelector(selector).getBoundingClientRect()
          return { x: box.x, y: box.y, right: box.right, bottom: box.bottom, height: box.height }
        }
        return { width: el.clientWidth, body: rect('.video-card-layout'), cover: rect('.video-card-cover'),
          reasons: rect('.video-card-reasons'), trend: rect('.video-card-inline-action button') }
      })
      assert.ok(positions.trend.height >= 44)
      assert.ok(positions.trend.bottom <= positions.body.bottom + 1)
      assert.ok(positions.reasons.bottom <= positions.body.bottom + 1)
      assert.ok(positions.trend.right <= positions.body.right + 1)
      assert.ok(positions.reasons.y >= positions.cover.bottom - 1)
      assert.ok(Math.abs(positions.reasons.x - positions.cover.x) < 1)
      await card.getByRole('button', { name: '观测趋势', exact: true }).click()
      await card.getByText(/数据积累中/).waitFor()
      await card.getByRole('button', { name: '收起趋势', exact: true }).click()
      const more = summary.getByRole('button', { name: '查看全部 →' })
      assert.ok((await more.boundingBox()).height >= 44)
      await more.focus()
      if (output) {
        await card.screenshot({ path: resolve(output, `${width}-${colorScheme}-dashboard-card.png`) })
        await summary.screenshot({ path: resolve(output, `${width}-${colorScheme}-dashboard-ranking.png`) })
        if (width === 1440 || width === 390) await page.screenshot({ path: resolve(output, `${width}-${colorScheme}-dashboard.png`), fullPage: true })
      }
      await more.press('Enter')
      await page.getByRole('heading', { level: 1, name: '鬼畜区排行榜', exact: true }).waitFor()
      assert.equal(await page.getByRole('link', { name: videos[6].title, exact: true }).count(), 1)
      assert.equal(await page.getByRole('button', { name: '观测趋势', exact: true }).count(), 7)
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
      assert.deepEqual(errors, [])
      console.log(`${width}px ${colorScheme}: summary=${Math.round(layout.width)}×${Math.round(layout.height)}, rows=${layout.rows.map(Math.round).join('/')}, complete ranking navigation passed`)
      await page.close()
    }
  }
} finally {
  await browser.close()
}
