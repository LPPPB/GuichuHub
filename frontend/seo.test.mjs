// @vitest-environment node
import { readFileSync } from 'node:fs'
import { JSDOM } from 'jsdom'
import { createElement } from 'react'
import { renderToString } from 'react-dom/server'
import { expect, it } from 'vitest'
import App from './src/App.jsx'

const source = new JSDOM(readFileSync(new URL('./index.html', import.meta.url), 'utf8')).window.document

it('declares crawlable site identity and local fallback icons in the initial head', () => {
  expect(source.title).toContain('GuichuHub')
  expect(source.querySelector('meta[name="description"]').content).toContain('鬼畜')
  expect(source.querySelector('link[rel="canonical"]').href).toBe('https://guichuhub.cn/')
  expect(source.querySelector('link[rel="icon"][type="image/x-icon"]').getAttribute('href')).toBe('/favicon.ico')
  expect(source.querySelector('link[rel="icon"][type="image/png"]').getAttribute('href')).toBe('/favicon-96x96.png')
  const website = JSON.parse(source.querySelector('script[type="application/ld+json"]').textContent)
  expect(website).toMatchObject({ '@context': 'https://schema.org', '@type': 'WebSite', name: 'GuichuHub', url: 'https://guichuhub.cn/', inLanguage: 'zh-CN' })
  expect(website.potentialAction).toBeUndefined() // There is no public search URL.
})

it('renders one meaningful home H1 without a browser or API access', () => {
  const document = new JSDOM(renderToString(createElement(App))).window.document
  expect([...document.querySelectorAll('h1')].map(node => node.textContent)).toEqual(['GuichuHub · B站鬼畜创作灵感看板'])
  expect(document.querySelector('main').textContent).toContain('热梗')
})

it('ships real PNG and multi-resolution ICO files rather than HTML fallbacks', () => {
  const png = readFileSync(new URL('./public/favicon-96x96.png', import.meta.url))
  expect(png.subarray(0, 8).toString('hex')).toBe('89504e470d0a1a0a')
  expect([png.readUInt32BE(16), png.readUInt32BE(20)]).toEqual([96, 96])
  const ico = readFileSync(new URL('./public/favicon.ico', import.meta.url))
  expect(ico.readUInt16LE(2)).toBe(1)
  expect(ico.readUInt16LE(4)).toBe(3)
  expect([0, 1, 2].map(index => ico[6 + index * 16])).toEqual([16, 32, 48])
  for (let index = 0; index < 3; index++) {
    const entry = 6 + index * 16
    const offset = ico.readUInt32LE(entry + 12)
    expect(ico.subarray(offset, offset + 8).toString('hex')).toBe('89504e470d0a1a0a')
  }
})
