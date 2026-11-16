import assert from 'node:assert/strict'
import {mkdir} from 'node:fs/promises'
import {chromium} from 'playwright-core'

// Local interaction proof. All API requests use synthetic fixtures, never tokens.
const browser=await chromium.launch({headless:true,channel:'msedge'})
try {
  const page=await browser.newPage({viewport:{width:1440,height:1000}})
  const errors=[]
  page.on('pageerror',e=>{errors.push(e.message);console.error('Browser error:',e.message)})
  let blocked=false,dashboardReads=0,savePayload
  await page.route('**/api/**',async route=>{
    const request=route.request(),path=new URL(request.url()).pathname
    let data=[],extra={}
    if(path==='/api/dashboard') {
      dashboardReads++
      data={kichu_rank:[],hot_memes:blocked?[]:[{keyword:'验收热梗',heat:100,related_videos:[]}],
        hot_songs:[],hot_videos:[],material_candidates:[],meme_materials:[],danmaku_words:[],comments_gold:[],last_updated:'2026-10-25 15:02:40'}
    } else if(path==='/api/auth/me')data={admin:true,via:'write_token',user:null}
    else if(path==='/api/status')data={crawling:false,meme_rules_version:blocked?2:1}
    else if(path==='/api/config/meme-stopwords') {
      if(request.method()==='PUT') {
        savePayload=request.postDataJSON()
        blocked=savePayload.categories['人工屏蔽'].includes('验收热梗')
        extra={effective:'immediate',message:'素材/热梗黑名单已立即生效'}
      }
      data={categories:{'人工屏蔽':blocked?['验收热梗']:[]}}
    } else if(path==='/api/config/meme-seed-words')data={words:[]}
    else if(path==='/api/config/tag-filters')data={categories:{},ad_keywords:[],activity_keywords:[],allowed_two_char:[]}
    else if(path==='/api/config/danmaku-filters')data={allowed_exact:[],bad_exact:[],bad_substr:[]}
    else if(path==='/api/config/word-rules/overview')data={}
    else if(path==='/api/admin/accounts')data={accounts:[],recent_logins:[]}
    else if(path==='/api/bili-auth/user')data=null
    else if(path==='/api/dev/stats')data={alembic_revision:'test',video_obs_batches:0,video_obs_rows:0,videos:0,ups:0,crawl_runs:{},stale_running:[]}
    await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({success:true,data,...extra})})
  })
  await page.goto(process.env.BLACKLIST_TEST_URL || 'http://127.0.0.1:5178/')
  await page.getByRole('heading',{name:'验收热梗',exact:true}).waitFor()
  await page.getByRole('button',{name:'开发者后台',exact:true}).click()
  await page.getByRole('button',{name:/词汇规则 公共底座/}).click()
  await page.getByRole('button',{name:/素材\/热梗/}).click()
  await page.getByPlaceholder('添加词（支持空格/逗号分隔多个）').fill('验收热梗')
  await page.getByTitle('添加',{exact:true}).click()
  const beforeSave=dashboardReads
  await page.getByRole('button',{name:'保存规则',exact:true}).click()
  await page.getByText('素材/热梗黑名单已立即生效',{exact:true}).waitFor()
  for(let attempt=0;dashboardReads<=beforeSave && attempt<20;attempt++)await page.waitForTimeout(50)
  assert.equal(dashboardReads,beforeSave+1)
  assert.deepEqual(savePayload,{categories:{'人工屏蔽':['验收热梗']}})
  await page.getByRole('navigation',{name:'主导航'}).getByRole('link',{name:'热梗',exact:true}).click()
  await page.getByText('暂无热梗数据',{exact:true}).waitFor()
  assert.equal(await page.getByRole('heading',{name:'验收热梗',exact:true}).count(),0)
  assert.deepEqual(errors,[])
  const directory=process.env.BLACKLIST_SCREENSHOT_DIR
  if(directory) {
    await mkdir(directory,{recursive:true})
    await page.screenshot({path:directory+'/blacklist-empty-after-save.png',fullPage:true,animations:'disabled'})
  }
  console.log(JSON.stringify({passed:true,savePayload,dashboardRefetchedImmediately:true,blockedHeadingAbsent:true,pageErrors:errors}))
} finally {await browser.close()}
