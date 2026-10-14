import assert from 'node:assert/strict'
import { mkdir, readFile } from 'node:fs/promises'
import { resolve, sep } from 'node:path'
import { chromium } from 'playwright-core'

// Production assets with synthetic responses only; never reads runtime or contacts the real API.
const root = resolve('dist')
const screenshotDir = process.env.LAYOUT_SCREENSHOT_DIR
const video = {
  bvid: 'BVnavigation', title: '【新宿决战】创作热点示例', author: '创作观察员', owner: { name: '创作观察员' },
  pic: 'https://fixture.test/cover.svg', views: 732000, likes: 31000, shares: 6000,
  comments: 320, danmaku: 120, duration: 100, pub_date: 1791936000, tname: '鬼畜剧场',
  speed: 14000, is_bursting: true, spark: [3, 5, 4, 7, 9, 12, 16],
}
const browser = await chromium.launch({
  headless: true,
  ...(process.env.LAYOUT_BROWSER_CHANNEL ? { channel: process.env.LAYOUT_BROWSER_CHANNEL } : {}),
  ...(process.env.LAYOUT_BROWSER_PATH ? { executablePath: process.env.LAYOUT_BROWSER_PATH } : {}),
})
try {
  if (screenshotDir) await mkdir(screenshotDir, { recursive: true })
  for (const theme of ['light', 'dark']) for (const width of [320, 390, 768, 1024, 1440]) {
    const page = await browser.newPage({ viewport: { width, height: 900 }, colorScheme: theme })
    const errors = []
    page.on('pageerror', error => errors.push(error.message))
    await page.route('**/*', async route => {
      const url = new URL(route.request().url())
      if (url.hostname === 'fixture.test' || url.pathname === '/api/proxy/image') return route.fulfill({ contentType: 'image/svg+xml', body:
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 100"><rect width="160" height="100" fill="#ccebf4"/><path d="m0 100 55-65 35 35 30-45 40 75" fill="#68aabf"/><circle cx="125" cy="24" r="12" fill="#fff1b4"/></svg>' })
      if (url.hostname !== 'navigation.test') return route.abort()
      if (url.pathname.startsWith('/api/')) {
        const data = url.pathname === '/api/dashboard' ? {
          kichu_rank: [video], hot_memes: [], hot_songs: [], hot_videos: [video],
          material_candidates: [], meme_materials: [], danmaku_words: [], comments_gold: [], last_updated: '2026-10-14 18:00',
        } : url.pathname === '/api/bursting-videos' ? { videos: [video,
          { ...video, bvid: 'BVsecond', title: '朋友的酒 · 灵感混剪', views: 245000, speed: 21000 },
          { ...video, bvid: 'BVthird', title: '今天也要找到新灵感', views: 121000, speed: 23000 }],
        } : url.pathname === '/api/auth/me' ? { admin: false, user: null } : []
        return route.fulfill({ json: { success: true, data } })
      }
      const path = resolve(root, url.pathname === '/' ? 'index.html' : `.${url.pathname}`)
      assert.ok(path.startsWith(root + sep))
      const contentType = path.endsWith('.js') ? 'application/javascript' : path.endsWith('.css') ? 'text/css' :
        path.endsWith('.svg') ? 'image/svg+xml' : 'text/html'
      return route.fulfill({ body: await readFile(path), contentType })
    })
    const settled = () => page.evaluate(async () => {
      await document.fonts.ready
      await Promise.all(document.getAnimations().filter(animation => Number.isFinite(animation.effect.getComputedTiming().iterations))
        .map(animation => animation.finished.catch(() => {})))
    })
    const screenshot = async name => {
      if (screenshotDir && [390, 1440].includes(width)) await page.screenshot({ path: resolve(screenshotDir, `${width}-${theme}-${name}.png`) })
    }
    await page.goto('https://navigation.test/')
    await page.getByRole('heading', { name: '正在爆发', exact: true }).waitFor()
    await settled()
    assert.equal(await page.locator('.site-brand').isVisible(), true)
    assert.equal(await page.locator('.site-sidebar').isVisible(), width >= 1024)
    assert.equal(await page.getByRole('button', { name: '打开导航菜单' }).isVisible(), width < 1024)
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
    const header = await page.locator('header').boundingBox()
    const main = await page.locator('main').boundingBox()
    assert.ok(main.y >= header.y + header.height - 1, 'Header must not cover content')
    const shortcutButtons = page.getByRole('navigation', { name: '快捷导航' }).getByRole('button')
    if (width < 1024) {
      const boxes = await Promise.all((await shortcutButtons.all()).map(button => button.boundingBox()))
      assert.equal(boxes.length, 4)
      assert.ok(boxes.every(box => Math.abs(box.y - boxes[0].y) < 1 && box.height >= 44), 'Four shortcuts must share one row with touch targets')
    }
    await screenshot('home')
    if (width < 1024) {
      await page.getByRole('button', { name: '打开导航菜单' }).click()
      const drawer = page.getByRole('dialog', { name: '站点导航' })
      await drawer.waitFor()
      await settled()
      assert.equal(await page.locator('.app-shell').getAttribute('inert'), '')
      assert.equal(await page.evaluate(() => document.body.style.overflow), 'hidden')
      await screenshot('drawer')
      await page.keyboard.press('Shift+Tab')
      assert.equal(await page.evaluate(() => document.activeElement.textContent.trim()), 'B 站账号登录')
      await page.keyboard.press('Tab')
      assert.equal(await page.evaluate(() => document.activeElement.getAttribute('aria-label')), '关闭导航菜单')
      await drawer.getByRole('button', { name: '热梗', exact: true }).click()
      await drawer.waitFor({ state: 'detached' })
      await page.getByRole('heading', { name: '热梗库', exact: true }).waitFor()
      assert.equal(await page.locator('.app-shell').getAttribute('inert'), null)
      assert.equal(await page.evaluate(() => document.body.style.overflow), '')
      await page.getByRole('button', { name: '打开导航菜单' }).click()
      await page.keyboard.press('Escape')
      await drawer.waitFor({ state: 'detached' })
      await page.getByRole('button', { name: '打开导航菜单' }).click()
      await page.setViewportSize({ width: 1100, height: 900 })
      await drawer.waitFor({ state: 'detached' })
      assert.equal(await page.locator('.app-shell').getAttribute('inert'), null)
      assert.equal(await page.evaluate(() => document.body.style.overflow), '')
      await page.setViewportSize({ width, height: 900 })
      await page.getByRole('button', { name: '打开导航菜单' }).click()
      await drawer.getByRole('button', { name: 'B 站账号登录' }).click()
      await drawer.waitFor({ state: 'detached' })
      await page.waitForFunction(() => document.activeElement?.getAttribute('aria-label') === '关闭登录')
      await page.getByRole('button', { name: '关闭登录' }).click()
      await page.getByRole('button', { name: 'GuichuHub 首页' }).click()
      await page.getByRole('heading', { name: '正在爆发', exact: true }).waitFor()
    }
    await page.evaluate(() => window.scrollTo(0, 650))
    assert.ok(Math.abs((await page.locator('header').boundingBox()).y) < 1, 'Brand must remain visible while scrolling')
    if (width >= 1024) {
      assert.ok(Math.abs((await page.locator('.site-sidebar').boundingBox()).y - header.height) < 2)
      await page.getByRole('navigation', { name: '主导航' }).getByRole('button', { name: '热梗', exact: true }).click()
      await page.getByRole('heading', { name: '热梗库', exact: true }).waitFor()
      assert.equal(await page.getByRole('navigation', { name: '主导航' }).getByRole('button', { name: '热梗', exact: true }).getAttribute('aria-current'), 'page')
    }
    assert.deepEqual(errors, [], 'No browser runtime errors')
    console.log(`${theme} ${width}px: brand, breakpoints, navigation, focus, scroll and overflow passed`)
    await page.close()
  }
} finally { await browser.close() }
