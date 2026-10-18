// @vitest-environment node
import { expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { JSDOM } from 'jsdom'
import { renderPublicPage, PUBLIC_ROUTES } from './ssr-entry'

const video={bvid:'BV1HYp16oE8v',title:'公开投稿样本',author:'公开作者样本',views:1000}
const template=readFileSync(new URL('../../index.html',import.meta.url),'utf8')
const fields={
  'kichu-rank':{kichu_rank:[video]},videos:{hot_videos:[video]},
  memes:{hot_memes:[{keyword:'热梗样本',heat:10}]},
  'meme-materials':{meme_materials:[{name:'素材库样本',description:'公开素材介绍',related_videos:[video]}]},
  songs:{hot_songs:[{bvid:video.bvid,name:'曲目样本',artist:'公开音乐作者',heat:9}]},
  materials:{material_candidates:[{...video,title:'发掘样本',material_reason:'公开推荐理由'}]},
  danmaku:{danmaku_words:[{word:'词云样本',count:10}],comments_gold:[{content:'高赞评论样本',author:'公开评论者',source_bvid:video.bvid,source_video:video.title}]},
  'up-trends':{up_analysis:{created_at:1792300000,tracked_up_count:1,up_details:[{mid:123,name:'公开作者样本'}],analysis:{summary:{total_ups:1,pool_total_videos:1,pool_total_views:1000},hot_videos:[video],play_ranking:[{mid:123,name:'公开作者样本',total_recent_views:1000}],keyword_cloud:[{text:'真实公开热词',value:42}],content_types:[{type:'鬼畜调教',count:3}],timeline:[{date:'10-18',count:2,views:300}]}}},
}
const sections=Object.fromEntries(Object.entries(fields).map(([tab,data])=>[tab,{status:'ready',content_version:tab,source_updated_at:null,data}]))
it.each([
  ['dashboard','公开投稿样本'],['kichu-rank','公开投稿样本'],['memes','热梗样本'],['videos','公开投稿样本'],
  ['meme-materials','素材库样本'],['songs','曲目样本'],['materials','发掘样本'],['danmaku','高赞评论样本'],['up-trends','公开作者样本'],
])('publishes %s with meaningful content and one primary heading',async(tab,title)=>{
  const route=PUBLIC_ROUTES.find(r=>r.tabId===tab)
  const bootstrap={schema_version:1,build_id:'test-build',tab_id:tab,sections,confirmed_at:{[tab]:1792300000},render_year:2026}
  const doc=new JSDOM(await renderPublicPage({route,bootstrap,template})).window.document
  expect(doc.querySelector('#root').textContent).toContain(title)
  expect(doc.querySelectorAll('h1')).toHaveLength(1)
  expect(doc.querySelector('time[datetime="2026-10-18T05:06:40.000Z"]')).not.toBeNull()
  if(tab==='up-trends') {
    expect(doc.querySelector('#root').textContent).toContain('公开投稿样本')
    expect(doc.querySelector('#root').textContent).toContain('真实公开热词')
    expect(doc.querySelector('#root').textContent).toContain('鬼畜调教')
    expect(doc.querySelector('#root').textContent).toContain('10-18')
  }
})

it('cached UP text and calendar year stay deterministic after minutes and across years',async()=>{
  vi.useFakeTimers({toFake:['Date']})
  try {
    const route=PUBLIC_ROUTES.find(r=>r.tabId==='up-trends')
    const bootstrap={schema_version:1,build_id:'test-build',tab_id:'up-trends',sections,confirmed_at:{},render_year:2026}
    vi.setSystemTime(new Date(1792300060*1000))
    const first=new JSDOM(await renderPublicPage({route,bootstrap,template})).window.document.querySelector('#root').textContent
    vi.setSystemTime(new Date(1792300180*1000))
    expect(new JSDOM(await renderPublicPage({route,bootstrap,template})).window.document.querySelector('#root').textContent).toBe(first)
    vi.setSystemTime(new Date('2027-01-01T00:05:00Z'))
    expect(new JSDOM(await renderPublicPage({route,bootstrap,template})).window.document.querySelector('#root').textContent).toBe(first)
  } finally {vi.useRealTimers()}
})
