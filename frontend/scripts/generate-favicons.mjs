import { readFile, writeFile } from 'node:fs/promises'
import { chromium } from 'playwright-core'

// Explicit maintenance command; generated files are committed. No browser is
// needed by the Docker build. Reuse the existing brand SVG without redesigning it.
const svg = await readFile('public/favicon.svg', 'utf8')
const browser = await chromium.launch({ headless: true,
  ...(process.env.LAYOUT_BROWSER_CHANNEL ? { channel: process.env.LAYOUT_BROWSER_CHANNEL } : {}),
  ...(process.env.LAYOUT_BROWSER_PATH ? { executablePath: process.env.LAYOUT_BROWSER_PATH } : {}),
})
try {
  const frames = []
  for (const size of [16, 32, 48, 96, 180]) {
    const page = await browser.newPage({ viewport: { width: size, height: size }, deviceScaleFactor: 1 })
    await page.setContent(`<style>html,body{margin:0;width:100%;height:100%;background:transparent}svg{display:block;width:100%;height:100%}</style>${svg}`)
    const png = await page.screenshot({ omitBackground: true })
    if (size <= 48) frames.push({ size, png })
    else await writeFile(`public/${size === 180 ? 'apple-touch-icon' : 'favicon-96x96'}.png`, png)
    await page.close()
  }
  const header = Buffer.alloc(6 + frames.length * 16)
  header.writeUInt16LE(1, 2)
  header.writeUInt16LE(frames.length, 4)
  let offset = header.length
  frames.forEach(({ size, png }, index) => {
    const entry = 6 + index * 16
    header[entry] = header[entry + 1] = size
    header.writeUInt16LE(1, entry + 4)
    header.writeUInt16LE(32, entry + 6)
    header.writeUInt32LE(png.length, entry + 8)
    header.writeUInt32LE(offset, entry + 12)
    offset += png.length
  })
  await writeFile('public/favicon.ico', Buffer.concat([header, ...frames.map(frame => frame.png)]))
  console.log('Generated ICO (16/32/48), PNG (96), and touch icon (180) from favicon.svg.')
} finally {
  await browser.close()
}
