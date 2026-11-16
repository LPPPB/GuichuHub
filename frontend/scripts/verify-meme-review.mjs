import {mkdir,writeFile,unlink} from 'node:fs/promises'
import {fileURLToPath} from 'node:url'
import {createServer} from 'vite'
import {chromium} from 'playwright-core'
import assert from 'node:assert/strict'
const root=fileURLToPath(new URL('../',import.meta.url))
process.chdir(root)
const output=fileURLToPath(new URL('../../.superpowers/sdd/meme-review-center/browser/',import.meta.url))
const html=root+'review-qa.html', entry=root+'review-qa.jsx'
await mkdir(output,{recursive:true})
await writeFile(html,'<html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><div id="root"></div><script type="module" src="/review-qa.jsx"></script></html>')
await writeFile(entry,`import React from 'react';import {createRoot} from 'react-dom/client';import MemeReviewCenter from './src/components/MemeReviewCenter';import {api} from './src/utils/api';import './src/index.css';
const rows=[{meme_id:'a',keyword:'大肥鱼',heat:335000,video_count:42},{meme_id:'b',keyword:'华强买瓜',heat:175000,video_count:26}];
api.getMemeSeedWords=async()=>({success:true,data:{words:['大肥鱼','华强买瓜'],version:2,links:{}}});
api.saveMemeSeedWords=async(words)=>({success:true,data:{words,version:3,links:{}}});
api.memeReview=async(path,method,body)=>({success:true,data:path==='overview'?{mode:'shadow',last_run:'2026-11-16-03',reviewed_run:'2026-11-15-15',needs_review:true,dictionary:[{id:'a',name:'大肥鱼',aliases:['大肥魚']},{id:'b',name:'华强买瓜',aliases:['买瓜']}],adjustments:[],preview:{boards:{hot_memes:rows,meme_materials:[]},candidates:{},source_times:{hot_memes:1794772800}},suspected_aliases:[{source:'a',target:'b',shared:3}]}:path==='preview'?{token:'qa',boards:{hot_memes:[],meme_materials:[]}}:path.startsWith('evidence')?{items:[{bvid:'BV1demo123456',raw_term:'大肥鱼',source:'tag',video:{title:'合成验收视频'}}],total:1}: {}});
createRoot(document.getElementById('root')).render(<div style={{background:'#f8fafc',padding:16,maxWidth:1300,margin:'auto'}}><MemeReviewCenter/></div>);`)
const server=await createServer({root,server:{host:'127.0.0.1',port:0}})
await server.listen()
const browser=await chromium.launch({headless:true,channel:'msedge'})
try {
 const page=await browser.newPage(), errors=[];page.on('pageerror',e=>errors.push(e.message))
 for(const width of [1440,390]) {
  await page.setViewportSize({width,height:1000});await page.goto(server.resolvedUrls.local[0]+'review-qa.html')
  await page.getByRole('button',{name:'隐藏 大肥鱼'}).waitFor()
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth), 'horizontal overflow')
  await page.screenshot({path:output+`review-${width}.png`,fullPage:true})
  await page.getByRole('button',{name:'隐藏 大肥鱼'}).click();await page.getByRole('button',{name:'预览调整'}).click()
  await page.getByRole('button',{name:'发布榜单调整'}).click();await page.getByRole('status').waitFor()
  await page.getByRole('button',{name:'梗词典',exact:true}).click();await page.getByLabel('待合并词条').selectOption('a');await page.getByLabel('保留词条').selectOption('b')
  await page.getByRole('button',{name:'加入合并预览'}).click();assert.ok(await page.getByText('词典：大肥鱼 → 华强买瓜').isVisible())
  await page.getByRole('button',{name:'采集种子词',exact:true}).click();await page.getByLabel('采集搜索词',{exact:true}).fill('大肥鱼\n朋友的酒')
  await page.getByRole('button',{name:'保存采集设置'}).click();await page.getByText('已保存采集设置，下次全量抓取生效').waitFor()
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth))
  await page.screenshot({path:output+`seeds-${width}.png`,fullPage:true})
 }
 assert.deepEqual(errors,[])
 console.log('Desktop/mobile: hide-preview-publish, dictionary merge staging, seed save, no overflow, no page errors passed.')
} finally {await browser.close();await server.close();await unlink(html);await unlink(entry)}
