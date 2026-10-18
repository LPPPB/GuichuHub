import assert from 'node:assert/strict'
import { mkdir, readFile } from 'node:fs/promises'
import { resolve, sep } from 'node:path'
import { chromium } from 'playwright-core'

// Run after npm run build. Uses only packaged assets and synthetic API responses;
// no local server, production requests, credentials, or runtime data are involved.
const root = resolve('dist')
const axes = ['播放规模', '观众认可', '收藏倾向', '讨论活跃', '分享倾向', '近期增速']
const video = {
  bvid: 'BVlayout', title: '烧心大赛！【AI全民制作人】长标题在手机端也应保持整齐易读', author: '很长的测试作者名字用于验证窄屏信息布局', views: 4197000,
  pub_date: 1700000000, tname: '鬼畜调教', trend_label: '上升期', likes: 180000, shares: 21000,
  description: '这里是视频简介，用于验证多行文本与关键数据之间的布局。',
  danmaku: 120, comments: 80, duration: 60, potential_score: 71,
  online_observation: { count: 392, display: '392', precision: 'exact', status: 'available', observed_at: 1700000000 },
  radar: { algorithm_version: 'radar-v2', observed_at: 1700000000, baseline_version: 'radar-v2-layout', axes: axes.map((label, i) => ({
    id: ['reach', 'approval', 'retention', 'discussion', 'sharing', 'growth'][i],
    label, score: 60, raw: 60, status: 'available', unit: i === 0 ? '次' : i === 5 ? '播放/小时' : '次/千播放',
    components: (i === 1 ? [{ id: 'likes_rate', label: '点赞', raw: 43, score: 80 }, { id: 'coins_rate', label: '投币', raw: 2, score: 40 }] :
      i === 3 ? [{ id: 'comments_rate', label: '评论', raw: 2, score: 50 }, { id: 'danmaku_rate', label: '弹幕', raw: 5, score: 70 }] :
      [{ id: 'demo', label, raw: 60, score: 60 }]).map(c => ({ ...c, reference: { count: 240, age_min_days: 0, age_max_days: 7 } })),
  })) },
}
const browser = await chromium.launch({
  headless: true,
  ...(process.env.LAYOUT_BROWSER_CHANNEL ? { channel: process.env.LAYOUT_BROWSER_CHANNEL } : {}),
  ...(process.env.LAYOUT_BROWSER_PATH ? { executablePath: process.env.LAYOUT_BROWSER_PATH } : {}),
})
try {
  if (process.env.LAYOUT_SCREENSHOT_DIR) {
    await mkdir(process.env.LAYOUT_SCREENSHOT_DIR, { recursive: true })
  }
  for (const width of [1920, 1280, 900, 390, 320]) {
    const page = await browser.newPage({ viewport: { width, height: 1000 } })
    await page.emulateMedia({ colorScheme: process.env.LAYOUT_COLOR_SCHEME || 'light' })
    await page.route('**/*', async route => {
      const url = new URL(route.request().url())
      if (url.hostname !== 'layout.test') return route.abort()
      if (url.pathname.startsWith('/api/')) {
        const data = url.pathname === '/api/dashboard' ? {
          kichu_rank: [0, 1, 2].map(i => ({ ...video, bvid: `BVlayout${i}` })), hot_videos: [video], hot_memes: [], hot_songs: [],
          material_candidates: [], meme_materials: [], danmaku_words: [], comments_gold: [],
        } : url.pathname === '/api/auth/me' ? null : []
        return route.fulfill({ json: { success: true, data } })
      }
      const path = resolve(root, url.pathname === '/' ? 'index.html' : `.${url.pathname}`)
      assert.ok(path.startsWith(root + sep))
      const contentType = path.endsWith('.js') ? 'application/javascript' :
        path.endsWith('.css') ? 'text/css' : 'text/html'
      return route.fulfill({ body: await readFile(path), contentType })
    })
    await page.goto('https://layout.test/')
    await page.getByRole('heading', { name: '鬼畜区排行榜', exact: true }).waitFor()
    assert.equal(await page.getByRole('img', { name: '视频数据雷达图' }).count(), 0)
    for (const name of ['鬼畜区排行榜', '鬼畜潜力视频']) {
      if (name === '鬼畜区排行榜') {
        await page.getByRole('button', { name: '查看全部 →' }).first().click()
      } else {
        await page.reload()
        await page.getByRole('heading', { name, exact: true }).waitFor()
        const section = page.locator('section').filter({ has: page.getByRole('heading', { name, exact: true }) })
        await section.getByRole('button', { name: '查看全部 →' }).click()
      }
      const card = page.locator('article').first()
      await card.waitFor()
      await page.evaluate(async () => {
        await document.fonts.ready
        await Promise.all(document.getAnimations().filter(animation =>
          Number.isFinite(animation.effect.getComputedTiming().iterations)
        ).map(animation => animation.finished.catch(() => {})))
      })
      const sizes = await card.evaluate(el => {
        const content = el.parentElement.parentElement
        const contentRect = content.getBoundingClientRect()
        const mainRect = document.querySelector('main').getBoundingClientRect()
        const style = getComputedStyle(content)
        return { card: el.getBoundingClientRect().width,
          content: contentRect.width, main: mainRect.width,
          contentCenter: contentRect.left + contentRect.width / 2,
          mainCenter: mainRect.left + mainRect.width / 2,
          padding: parseFloat(style.paddingLeft) + parseFloat(style.paddingRight),
          overflow: document.documentElement.scrollWidth > window.innerWidth }
      })
      assert.ok(sizes.content >= Math.min(sizes.main, 1400) - 2,
        `${width}px ${name}: content shrank: ${JSON.stringify(sizes)}`)
      assert.equal(sizes.overflow, false, `${width}px ${name}: horizontal overflow`)
      assert.ok(sizes.content <= 1401, `${width}px ${name}: maximum width exceeded`)
      assert.ok(Math.abs(sizes.contentCenter - sizes.mainCenter) < 2,
        `${width}px ${name}: content not centered`)
      assert.ok(Math.abs(sizes.card - (sizes.content - sizes.padding)) < 2,
        `${width}px ${name}: card does not fill the content area`)
      const radar = page.locator('.kb-video-radar-slot').first()
      const cardContentWidth = await card.evaluate(el => el.clientWidth -
        parseFloat(getComputedStyle(el).paddingLeft) - parseFloat(getComputedStyle(el).paddingRight))
      assert.equal(await radar.isVisible(), cardContentWidth >= 820,
        `${width}px ${name}: radar visibility does not match available width`)
      assert.equal(await radar.isVisible(), width >= 1280,
        `${width}px ${name}: unexpected radar at a regression viewport`)
      if (name === '鬼畜区排行榜') {
        if (width >= 1280) {
          await radar.getByRole('button', { name: '观众认可详情' }).click()
          await radar.getByRole('dialog', { name: '观众认可' }).waitFor()
          await page.waitForFunction(() => Number(document.querySelector('.kb-video-radar-slot [data-testid="radar-data-polygon"]').getAttribute('points').split(' ')[0].split(',')[1]) <= 50.85)
          await radar.getByRole('button', { name: '关闭详情' }).click({ trial: true, timeout: 1200 })
          if (process.env.LAYOUT_SCREENSHOT_DIR) await page.screenshot({ path: resolve(process.env.LAYOUT_SCREENSHOT_DIR, `${width}-radar-detail.png`) })
          await page.keyboard.press('Escape')
        } else {
          await card.getByRole('button', { name: '视频表现', exact: true }).click()
          const portrait = card.locator('.video-card-mobile-portrait')
          await portrait.getByRole('button', { name: '分享倾向详情' }).click()
          await portrait.getByRole('dialog', { name: '分享倾向' }).waitFor()
          await page.waitForFunction(() => Number(document.querySelector('.video-card-mobile-portrait [data-testid="radar-data-polygon"]').getAttribute('points').split(' ')[0].split(',')[1]) <= 50.85)
          assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
          if (process.env.LAYOUT_SCREENSHOT_DIR) await page.screenshot({ path: resolve(process.env.LAYOUT_SCREENSHOT_DIR, `${width}-portrait-detail.png`) })
          await card.getByRole('button', { name: '收起表现', exact: true }).click()
        }
      }
      const status = await card.locator('.video-card-status').evaluate(el => ({
        height: el.clientHeight, line: parseFloat(getComputedStyle(el).lineHeight),
      }))
      assert.ok(status.height < status.line * 2, 'Status must remain one line')
      for (const button of await card.locator('.video-card-actions button').all()) {
        if (!await button.isVisible()) continue
        const box = await button.boundingBox()
        const actionBounds = await card.locator('.video-card-actions').boundingBox()
        // Preserve the deployed compact footer; dashboard inline actions are checked separately at 44px.
        const minimumHeight = sizes.card < 560 ? 36 : 44
        assert.ok(box.height >= minimumHeight && box.x >= 0 && box.x + box.width <= width,
          `${width}px: action must fit the viewport and have a ${minimumHeight}px touch target: ${JSON.stringify(box)}`)
        assert.ok(box.x >= actionBounds.x - 1 && box.x + box.width <= actionBounds.x + actionBounds.width + 1,
          `${width}px: action must fit its card action row: ${JSON.stringify(box)}`)
      }
      assert.equal(await card.locator('.video-card-views').evaluate(el => getComputedStyle(el).color), 'rgb(251, 114, 153)')
      await card.getByRole('button', { name: '观测趋势', exact: true }).click()
      await card.getByText(/数据积累中/).waitFor()
      assert.equal(page.url(), 'https://layout.test/')
      await card.getByRole('button', { name: '收起趋势', exact: true }).click()
      console.log(`${width}px ${name}: card=${Math.round(sizes.card)}px radar=${await radar.isVisible()}`)
      if (process.env.LAYOUT_SCREENSHOT_DIR) {
        await page.evaluate(async () => {
          await document.fonts.ready
          await Promise.all(document.getAnimations().filter(animation =>
            Number.isFinite(animation.effect.getComputedTiming().iterations)
          ).map(animation => animation.finished.catch(() => {})))
        })
        await page.screenshot({ path: resolve(process.env.LAYOUT_SCREENSHOT_DIR,
          `${width}-${name === '鬼畜区排行榜' ? 'ranking' : 'potential'}.png`) })
      }
    }
    await page.close()
  }
} finally {
  await browser.close()
}
