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
  for (const theme of ['light', 'dark']) for (const width of [319, 320, 390, 768, 1024, 1046, 1440]) {
    const height = [319, 1046].includes(width) ? 701 : 900
    const page = await browser.newPage({ viewport: { width, height }, colorScheme: theme })
    const errors = []
    let fixtureMember = false
    page.on('pageerror', error => errors.push(error.message))
    await page.route('**/*', async route => {
      const url = new URL(route.request().url())
      if (url.hostname === 'fixture.test' || url.pathname === '/api/proxy/image') return route.fulfill({ contentType: 'image/svg+xml', body:
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 100"><rect width="160" height="100" fill="#ccebf4"/><path d="m0 100 55-65 35 35 30-45 40 75" fill="#68aabf"/><circle cx="125" cy="24" r="12" fill="#fff1b4"/></svg>' })
      if (url.hostname !== 'navigation.test') return route.abort()
      if (url.pathname.startsWith('/api/')) {
        if (url.pathname === '/api/bili-auth/logout') fixtureMember = false
        const data = url.pathname === '/api/dashboard' ? {
          kichu_rank: [video], hot_memes: [], hot_songs: [], hot_videos: [video],
          material_candidates: [], meme_materials: [], danmaku_words: [], comments_gold: [], last_updated: '2026-10-14 18:00',
        } : url.pathname === '/api/bursting-videos' ? { videos: [video,
          { ...video, bvid: 'BVsecond', title: '朋友的酒 · 灵感混剪', views: 245000, speed: 21000 },
          { ...video, bvid: 'BVthird', title: '今天也要找到新灵感', views: 121000, speed: 23000 }],
        } : url.pathname === '/api/auth/me' ? { admin: fixtureMember, user: fixtureMember ? { name: '示例站长' } : null } : []
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
      if (screenshotDir && [319, 390, 1046, 1440].includes(width)) await page.screenshot({ path: resolve(screenshotDir, `${width}-${theme}-${name}.png`) })
    }
    await page.goto('https://navigation.test/')
    await page.getByRole('heading', { name: '正在爆发', exact: true }).waitFor()
    await settled()
    assert.equal(await page.locator('.site-header').isVisible(), width < 1024)
    assert.equal(await page.locator('.site-brand').isVisible(), width < 1024)
    assert.equal(await page.locator('.site-sidebar').isVisible(), width >= 1024)
    assert.equal(await page.getByRole('button', { name: '打开导航菜单' }).isVisible(), width < 1024)
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
    const header = await page.locator('header').boundingBox() || { y: 0, height: 0 }
    const main = await page.locator('main').boundingBox()
    assert.ok(main.y >= header.y + header.height - 1, 'Header must not cover content')
    if (width >= 1024) {
      assert.ok(main.y < 1, 'Desktop must not retain an empty header row')
      assert.ok((await page.locator('.site-sidebar').boundingBox()).height >= height - 34, 'Desktop island should reclaim header height')
    }
    const shortcutButtons = page.getByRole('navigation', { name: '快捷导航' }).getByRole('button')
    if (width < 1024) {
      const boxes = await Promise.all((await shortcutButtons.all()).map(button => button.boundingBox()))
      assert.equal(boxes.length, 3)
      assert.deepEqual((await shortcutButtons.allTextContents()).map(text => text.trim()), ['鬼畜榜', '潜力视频', 'UP 主动态'])
      assert.ok(boxes.every(box => Math.abs(box.y - boxes[0].y) < 1 && box.height >= 44), 'Three shortcuts must share one row with touch targets')
    }
    await screenshot('home')
    if (width >= 1024) {
      const island = page.locator('.site-sidebar')
      const collapse = page.getByRole('button', { name: '收起侧边栏' })
      const islandBox = await island.boundingBox()
      const buttonBox = await collapse.boundingBox()
      assert.ok(islandBox.x >= 12 && islandBox.y >= header.height + 12, 'Island must have space from page edges')
      assert.ok(buttonBox.y - islandBox.y < 120, 'Collapse control belongs near the top of the island')
      assert.equal(await island.evaluate(el => getComputedStyle(el).borderRightWidth), '0px')
      assert.equal(await island.evaluate(el => getComputedStyle(el).boxShadow.includes('0px 0px 0px 1px')), false, 'Island shadow must not recreate an outline')
      await collapse.hover()
      const hoverBox = await collapse.boundingBox()
      assert.ok(Math.abs(hoverBox.x - buttonBox.x) < 1 && Math.abs(hoverBox.y - buttonBox.y) < 1, 'Collapse control must not move on hover')
      const expandedMain = await page.locator('main').boundingBox()
      await collapse.click()
      await settled()
      assert.ok((await island.boundingBox()).width <= 80)
      assert.ok((await page.locator('main').boundingBox()).x < expandedMain.x - 100, 'Collapsing must release content width')
      const iconCenters = await island.locator('nav button > svg, [data-sidebar-actions] button > svg').evaluateAll(icons => icons.map(icon => {
        const box = icon.getBoundingClientRect(); return box.left + box.width / 2
      }))
      assert.ok(iconCenters.every(center => Math.abs(center - iconCenters[0]) < 1), 'Collapsed navigation and action icons must share one center line')
      const navigation = page.getByRole('navigation', { name: '主导航' })
      for (const name of ['总览', '鬼畜榜', '梗素材库', '弹幕 & 评论']) {
        assert.equal(await navigation.getByRole('button', { name, exact: true }).isVisible(), true, `${name} must remain reachable`)
      }
      await screenshot('collapsed')
      await page.setViewportSize({ width: 390, height: 900 })
      await page.getByRole('button', { name: '打开导航菜单' }).click()
      const drawer = page.getByRole('dialog', { name: '站点导航' })
      assert.equal(await drawer.getByRole('button', { name: '潜力视频', exact: true }).innerText(), '潜力视频')
      await page.keyboard.press('Escape')
      await drawer.waitFor({ state: 'detached' })
      await page.setViewportSize({ width, height })
      await page.getByRole('button', { name: '展开侧边栏' }).click()
      await settled()
      assert.ok((await island.boundingBox()).width >= 248)
    }
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
      await page.setViewportSize({ width, height })
      await page.getByRole('button', { name: '打开导航菜单' }).click()
      await drawer.getByRole('button', { name: 'B 站账号登录' }).click()
      await drawer.waitFor({ state: 'detached' })
      await page.waitForFunction(() => document.activeElement?.getAttribute('aria-label') === '关闭登录')
      await page.getByRole('button', { name: '关闭登录' }).click()
      await page.getByRole('button', { name: 'GuichuHub 首页' }).click()
      await page.getByRole('heading', { name: '正在爆发', exact: true }).waitFor()
    }
    await page.evaluate(() => window.scrollTo(0, 650))
    if (width < 1024) assert.ok(Math.abs((await page.locator('header').boundingBox()).y) < 1, 'Narrow-screen brand must remain visible while scrolling')
    if (width >= 1024) {
      assert.ok(Math.abs((await page.locator('.site-sidebar').boundingBox()).y - header.height - 16) < 2)
      await page.getByRole('navigation', { name: '主导航' }).getByRole('button', { name: '热梗', exact: true }).click()
      await page.getByRole('heading', { name: '热梗库', exact: true }).waitFor()
      assert.equal(await page.getByRole('navigation', { name: '主导航' }).getByRole('button', { name: '热梗', exact: true }).getAttribute('aria-current'), 'page')
    }
    assert.deepEqual(errors, [], 'No browser runtime errors')
    if (width === 1440) {
      fixtureMember = true
      await page.reload()
      await page.getByRole('button', { name: '刷新数据', exact: true }).waitFor()
      await settled()
      await screenshot('admin-home')
      const verifyAccountMenu = async container => {
        await container.getByRole('button', { name: /示例站长/ }).click()
        const logout = container.getByRole('button', { name: '退出登录' })
        const box = await logout.boundingBox()
        assert.ok(box.y >= 0 && box.y + box.height <= 900, 'Account menu must fit the viewport')
        await logout.click({ trial: true, timeout: 1500 })
        await container.locator('.fixed.inset-0.z-10').click({ position: { x: 4, y: 4 } })
      }
      await verifyAccountMenu(page.locator('.site-sidebar'))
      const getStyles = button => button.evaluate(el => {
        const style = getComputedStyle(el)
        return Object.fromEntries(['fontSize', 'fontWeight', 'color', 'backgroundColor', 'borderColor', 'borderRadius',
          'paddingTop', 'paddingRight', 'paddingBottom', 'paddingLeft'].map(key => [key, style[key]]))
      })
      const originalStyles = {}
      for (const name of ['我的收藏', '刷新数据', theme === 'dark' ? '切换到日间模式' : '切换到夜间模式']) {
        originalStyles[name] = await getStyles(page.locator('.site-sidebar').getByRole('button', { name, exact: true }))
      }
      await page.setViewportSize({ width: 390, height: 900 })
      await page.getByRole('button', { name: '打开导航菜单' }).click()
      const drawer = page.getByRole('dialog', { name: '站点导航' })
      await settled()
      for (const [name, style] of Object.entries(originalStyles)) {
        assert.deepEqual(await getStyles(drawer.getByRole('button', { name, exact: true })), style, `${name}: drawer must preserve the original sidebar UI`)
      }
      const drawerBox = await drawer.boundingBox()
      await verifyAccountMenu(drawer)
      assert.equal(drawerBox.x, 0, 'Drawer must attach to the viewport edge')
      assert.equal(await drawer.evaluate(el => getComputedStyle(el).borderRadius), '0px', 'Drawer must not use an island frame')
      if (screenshotDir) await page.screenshot({ path: resolve(screenshotDir, `390-${theme}-admin-drawer.png`) })
      await drawer.getByRole('button', { name: /示例站长/ }).click()
      await drawer.getByRole('button', { name: '退出登录' }).click()
      await drawer.getByRole('button', { name: 'B 站账号登录' }).waitFor()
      assert.equal(await drawer.getByRole('button', { name: '刷新数据', exact: true }).count(), 0)
      assert.deepEqual(errors, [])
    }
    console.log(`${theme} ${width}px: brand, breakpoints, navigation, focus, scroll and overflow passed`)
    await page.close()
  }
} finally { await browser.close() }
