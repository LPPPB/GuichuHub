import assert from 'node:assert/strict'
import { mkdir, readFile } from 'node:fs/promises'
import { resolve, sep } from 'node:path'
import { chromium } from 'playwright-core'

// Packaged UI + intercepted, synthetic API responses. No running backend or real login.
const root = resolve('dist')
const output = process.env.DEMO_SCREENSHOT_DIR
const browser = await chromium.launch({ headless: true,
  ...(process.env.LAYOUT_BROWSER_CHANNEL ? { channel: process.env.LAYOUT_BROWSER_CHANNEL } : {}),
  ...(process.env.LAYOUT_BROWSER_PATH ? { executablePath: process.env.LAYOUT_BROWSER_PATH } : {}),
})
try {
  if (output) await mkdir(output, { recursive: true })
  for (const [width, theme, motion] of [[1440, 'light'], [390, 'light'], [320, 'light'], [390, 'dark'], [390, 'light', 'reduce']]) {
    const page = await browser.newPage({ viewport: { width, height: 1000 },
      colorScheme: theme, reducedMotion: motion || 'no-preference' })
    const errors = []
    const writes = []
    page.on('pageerror', error => errors.push(error.message))
    await page.route('**/*', async route => {
      const request = route.request()
      const url = new URL(request.url())
      if (url.hostname !== 'demo.test') return route.abort()
      if (url.pathname.startsWith('/api/')) {
        if (request.method() !== 'GET') writes.push(`${request.method()} ${url.pathname}`)
        const data = url.pathname === '/api/auth/me' ? { admin: true, user: { mid: 'demo', name: '演示管理员' } } :
          url.pathname === '/api/dashboard' ? { kichu_rank: [], hot_videos: [], hot_memes: [], hot_songs: [] } :
          url.pathname === '/api/status' ? { crawling: false } : null
        return route.fulfill({ json: { success: data != null, data, message: '离线样例未提供此模块的数据' } })
      }
      const file = resolve(root, url.pathname === '/' ? 'index.html' : `.${url.pathname}`)
      assert.ok(file.startsWith(root + sep))
      const contentType = file.endsWith('.js') ? 'application/javascript' : file.endsWith('.css') ? 'text/css' :
        file.endsWith('.svg') ? 'image/svg+xml' : file.endsWith('.png') ? 'image/png' : 'text/html'
      return route.fulfill({ body: await readFile(file), contentType })
    })
    await page.goto('https://demo.test/')
    if (width < 1024) await page.getByRole('button', { name: '打开导航菜单' }).click()
    await page.getByRole('button', { name: '开发者后台', exact: true }).click()
    await page.getByRole('button', { name: /示例演示/ }).click().catch(error => {
      throw new Error(`${error.message}; runtime errors: ${JSON.stringify(errors)}`)
    })
    await page.getByRole('button', { name: '视频雷达图', exact: true }).click()
    const demo = page.getByRole('region', { name: '视频雷达图' })
    await demo.waitFor()
    const settled = async score => {
      await demo.getByRole('img', { name: '视频数据雷达图' }).scrollIntoViewIfNeeded()
      await page.waitForFunction(expected => {
      const node = document.querySelector('.radar-demo [data-testid="radar-data-polygon"]')
      const y = Number(node?.getAttribute('points').split(' ')[0].split(',')[1])
      return Number.isFinite(y) && Math.abs(y - (82 - 52 * expected / 100)) < 0.03
      }, score)
    }
    await settled(68)
    assert.equal(await demo.getByRole('img', { name: '视频数据雷达图' }).isVisible(), true)
    const checkFit = async () => {
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, `${width}px: page overflow`)
      for (const button of await demo.getByRole('button').all()) {
        if (!await button.isVisible()) continue
        const box = await button.boundingBox()
        assert.ok(box.x >= 0 && box.x + box.width <= width + 1, `${width}px: button overflow`)
      }
    }
    await checkFit()
    if (output) {
      await page.screenshot({ path: resolve(output, `${width}-${theme}-${motion || 'animated'}.png`), fullPage: true })
      await demo.screenshot({ path: resolve(output, `preview-${width}-${theme}-${motion || 'animated'}.png`) })
    }
    await demo.getByRole('button', { name: '样本不足', exact: true }).click()
    assert.equal(await demo.locator('[data-testid="radar-data-polygon"]').count(), 0)
    assert.equal(await demo.getByRole('slider', { name: '收藏倾向' }).isDisabled(), true)
    await demo.getByRole('button', { name: '收藏倾向详情' }).click()
    assert.match(await demo.getByRole('dialog').innerText(), /参考样本不足/)
    await checkFit()
    await demo.getByRole('button', { name: '关闭详情' }).click()
    await demo.getByRole('button', { name: '真实零分', exact: true }).click()
    await settled(68)
    assert.match(await demo.locator('[data-testid="radar-data-polygon"]').getAttribute('points'), /82.00,82.00/)
    const slider = demo.getByRole('slider', { name: '播放规模' })
    await slider.focus()
    await slider.press('End')
    assert.equal(await slider.inputValue(), '100')
    await settled(100)
    await demo.getByRole('button', { name: '重播展开动画' }).click()
    await settled(100)
    await demo.getByRole('button', { name: '重置样例' }).click()
    assert.equal(await slider.inputValue(), '68')
    assert.deepEqual(writes, [], 'Demo must not write data')
    assert.deepEqual(errors, [], 'Page runtime errors')
    console.log(`${width}px ${theme} ${motion || 'animated'}: navigation, layout, missing/zero, details, keyboard, replay, reset passed`)
    await page.close()
  }
} finally { await browser.close() }
