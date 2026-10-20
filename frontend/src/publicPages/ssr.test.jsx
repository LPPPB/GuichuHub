// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { JSDOM } from 'jsdom'
import { readFileSync } from 'node:fs'
import { renderPublicPage } from './ssr-entry'
import { serializeBootstrap, validateBootstrap } from './contract'

const template = readFileSync(new URL('../../index.html', import.meta.url), 'utf8')
const video = {bvid: 'BV1HYp16oE8v', title: '合成鬼畜榜作品', author:'公开作者', views:1000}
export function fixture(tab = 'kichu-rank') {
  return {schema_version:1, build_id:'test-build', tab_id:tab, render_year:2026, confirmed_at:{}, sections:{
    'kichu-rank': {status:'ready',content_version:'v1',source_updated_at:null,data:{kichu_rank:[video]}},
    videos: {status:'ready',content_version:'v2',source_updated_at:null,data:{hot_videos:[{...video,title:'合成潜力作品'}]}},
    memes: {status:'ready',content_version:'v3',source_updated_at:null,data:{hot_memes:[{keyword:'合成热梗',heat:10}]}},
  }}
}
describe('initial public HTML', () => {
  it.each([
    ['kichu-rank', '/rankings/kichu', '合成鬼畜榜作品'],
    ['videos', '/rankings/potential', '合成潜力作品'],
    ['memes', '/memes', '合成热梗'],
  ])('renders %s without effects or API calls', async (tab, path, title) => {
    const html = await renderPublicPage({route:{tabId:tab,path}, bootstrap:fixture(tab), template})
    const doc = new JSDOM(html).window.document
    expect(doc.querySelector('#root').textContent).toContain(title)
    expect(doc.querySelectorAll('h1')).toHaveLength(1)
    expect(doc.querySelector('link[rel="canonical"]').href).toBe('https://guichuhub.cn'+path)
    expect(doc.title).not.toBe('')
    expect(doc.querySelector('a[href="/memes"]')).not.toBeNull()
    expect(JSON.parse(doc.querySelector('#public-page-bootstrap').textContent).tab_id).toBe(tab)
  })
  it('round trips hostile strings without ending the bootstrap script', () => {
    const data = fixture()
    data.sections['kichu-rank'].data.kichu_rank[0].title = '</script><script>alert(1)</script>\u2028\u2029<'
    const json = serializeBootstrap(data)
    expect(json).not.toContain('<')
    expect(json).not.toContain('\u2028')
    expect(JSON.parse(json)).toEqual(data)
  })
  it('rejects malformed bootstrap and future versions', () => {
    expect(validateBootstrap({...fixture(),schema_version:2})).toBeNull()
    expect(validateBootstrap({...fixture(),tab_id:'dev'})).toBeNull()
    expect(validateBootstrap({...fixture(),build_id:'../evil'})).toBeNull()
    expect(validateBootstrap(fixture())).not.toBeNull()
  })
})
