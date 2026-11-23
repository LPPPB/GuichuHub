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
const candidates=[{meme_id:'c',keyword:'二仙桥',heat:400000,video_count:48}];
api.getMemeSeedWords=async()=>({success:true,data:{words:['大肥鱼','华强买瓜'],version:2,links:{}}});
api.saveMemeSeedWords=async(words)=>({success:true,data:{words,version:3,links:{}}});
api.memeReview=async(path,method,body)=>({success:true,data:path==='overview'?{mode:'shadow',last_run:'2026-11-16-03',reviewed_run:'2026-11-15-15',needs_review:true,dictionary:[{id:'a',name:'大肥鱼',aliases:['大肥魚']},{id:'b',name:'华强买瓜',aliases:['买瓜']},{id:'c',name:'二仙桥',aliases:[]}],adjustments:[],preview:{boards:{hot_memes:rows,meme_materials:[]},base_boards:{hot_memes:rows,meme_materials:[]},candidates:{hot_memes:candidates},source_times:{hot_memes:1794772800}},suspected_aliases:[{source:'a',target:'b',shared:3}]}:path==='preview'?{token:'qa',boards:{hot_memes:[rows[0],...candidates],meme_materials:[]}}:path.startsWith('evidence')?{items:[{bvid:'BV1demo123456',raw_term:'大肥鱼',source:'tag',video:{title:'合成验收视频'}}],total:1}: {}});
createRoot(document.getElementById('root')).render(<div style={{background:'#f8fafc',padding:16,maxWidth:1300,margin:'auto'}}><MemeReviewCenter/></div>);`)
const server=await createServer({root,server:{host:'127.0.0.1',port:0}})
await server.listen()
const browser=await chromium.launch({headless:true,channel:'msedge'})
try {
 const page=await browser.newPage(), errors=[];page.on('pageerror',e=>errors.push(e.message))
 for(const width of [1440,390]) {
  await page.setViewportSize({width,height:1000});await page.goto(server.resolvedUrls.local[0]+'review-qa.html')
  const chosen=page.getByRole('region',{name:'选择区'})
  const available=page.getByRole('region',{name:'备选区'})
  const chosenNames=()=>chosen.getByRole('heading',{level:4}).allTextContents()
  await chosen.getByRole('heading',{name:'大肥鱼'}).waitFor()
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth), 'horizontal overflow')
  await page.screenshot({path:output+`review-${width}.png`,fullPage:true})
  if (width===1440) await available.getByLabel('拖动 二仙桥').dragTo(chosen.getByRole('heading',{level:3}))
  else await available.getByRole('button',{name:'加入选择区 二仙桥'}).click()
  assert.deepEqual(await chosenNames(),['二仙桥','大肥鱼','华强买瓜'])
  if (width===1440) {
   const first=chosen.getByLabel('拖动 大肥鱼')
   const target=chosen.getByRole('listitem').first()
   await first.dragTo(target,{targetPosition:{x:12,y:3}})
  } else {
   await chosen.getByRole('button',{name:'上移 大肥鱼'}).click()
  }
  assert.deepEqual(await chosenNames(),['大肥鱼','二仙桥','华强买瓜'])
  if (width===1440) {
   const list=chosen.getByRole('list')
   const [listBox,firstBox,secondBox]=await Promise.all([
    list.boundingBox(),chosen.getByRole('listitem').nth(0).boundingBox(),chosen.getByRole('listitem').nth(1).boundingBox(),
   ])
   const gap=(firstBox.y+firstBox.height+secondBox.y)/2-listBox.y
   await chosen.getByLabel('拖动 华强买瓜').dragTo(list,{targetPosition:{x:20,y:gap}})
   assert.deepEqual(await chosenNames(),['大肥鱼','华强买瓜','二仙桥'])
  }
  await chosen.getByRole('button',{name:'移回备选 华强买瓜'}).click()
  await available.getByRole('heading',{name:'华强买瓜'}).waitFor()
  await page.getByRole('button',{name:'预览调整'}).click()
  await page.getByRole('button',{name:'发布榜单调整'}).click();await page.getByRole('status').waitFor()
  await page.getByRole('button',{name:'梗词典',exact:true}).click();await page.getByLabel('待合并词条').selectOption('a');await page.getByLabel('保留词条').selectOption('b')
  await page.getByRole('button',{name:'加入合并预览'}).click();await page.getByText('待发布 1 项').click()
  assert.ok(await page.getByText('词典：大肥鱼 → 华强买瓜').isVisible())
  await page.getByRole('button',{name:'采集种子词',exact:true}).click();await page.getByLabel('采集搜索词',{exact:true}).fill('大肥鱼\n朋友的酒')
  await page.getByRole('button',{name:'保存采集设置'}).click();await page.getByText('已保存采集设置，下次全量抓取生效').waitFor()
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth))
  await page.screenshot({path:output+`seeds-${width}.png`,fullPage:true})
 }
 const tablet=await browser.newPage({viewport:{width:1180,height:900},hasTouch:true})
 tablet.on('pageerror',e=>errors.push(e.message))
 await tablet.goto(server.resolvedUrls.local[0]+'review-qa.html')
 const tabletChosen=tablet.getByRole('region',{name:'选择区'})
 const handle=tablet.getByRole('region',{name:'备选区'}).getByLabel('拖动 二仙桥')
 await handle.waitFor()
 const [start,end]=await Promise.all([handle.boundingBox(),tabletChosen.getByRole('heading',{level:3}).boundingBox()])
 const touch=await tablet.context().newCDPSession(tablet)
 const from={x:start.x+start.width/2,y:start.y+start.height/2}
 const to={x:end.x+end.width/2,y:end.y+end.height/2}
 await touch.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[from]})
 await touch.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[to]})
 await touch.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]})
 await tabletChosen.getByRole('heading',{name:'二仙桥'}).waitFor()
 assert.equal(await tabletChosen.getByRole('heading',{level:4}).first().textContent(),'二仙桥')
 await tablet.close()
 assert.deepEqual(errors,[])
 console.log('Desktop/mobile/tablet: drag or tap to select, manual reorder, remove, preview/publish, dictionary and seeds passed without page errors or overflow.')
} finally {await browser.close();await server.close();await unlink(html);await unlink(entry)}
