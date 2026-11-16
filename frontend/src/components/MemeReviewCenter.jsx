import {useEffect, useRef, useState} from 'react'
import {api} from '../utils/api'

const empty = () => ({dictionary:[], adjustments:[]})
const tabs = [['today','今日待办'],['adjustments','当前调整'],['dictionary','梗词典'],['seeds','采集种子词']]
const labels = {hot_memes:'热梗库',meme_materials:'梗素材库'}
const actions = {hide:'隐藏',add:'补录',position:'调序',revoke:'撤销'}
const field = 'border border-slate-300 rounded-lg px-3 py-2 bg-white min-w-0 text-sm'
const button = 'border border-slate-300 rounded-lg px-3 py-2 text-sm bg-white hover:bg-slate-50 disabled:opacity-40'
const date = ts => ts ? new Date(ts*1000).toLocaleString('zh-CN') : '暂无'
const nameOf = row => row.keyword || row.name || row.meme_id
const wordsOf = text => [...new Set(text.split(/[\n,，]+/).map(w=>w.trim()).filter(Boolean))]

export default function MemeReviewCenter({initialTab='today', onRules}) {
  const [tab,setTab]=useState(initialTab), [board,setBoard]=useState('hot_memes')
  const [data,setData]=useState(null), [proposal,setProposal]=useState(empty)
  const [preview,setPreview]=useState(null), [message,setMessage]=useState(''), [error,setError]=useState('')
  const [busy,setBusy]=useState(false), [draftRevision,setDraftRevision]=useState(0)
  const [seedText,setSeedText]=useState(''), [seedVersion,setSeedVersion]=useState(null), [seedLinks,setSeedLinks]=useState({})
  const [query,setQuery]=useState(''), [editName,setEditName]=useState(''), [editAliases,setEditAliases]=useState(''), [editing,setEditing]=useState(null)
  const [mergeSource,setMergeSource]=useState(''), [mergeTarget,setMergeTarget]=useState('')
  const [seedCandidate,setSeedCandidate]=useState(null), [seedSearch,setSeedSearch]=useState('')
  const [blockedSeeds,setBlockedSeeds]=useState([]), [manualBvids,setManualBvids]=useState({})
  const [cleanup,setCleanup]=useState(null), [undo,setUndo]=useState(null), [evidence,setEvidence]=useState(null)
  const initialized=useRef(false), requestId=useRef(null)
  useEffect(()=>setTab(initialTab),[initialTab])
  const check=res=>{if(!res.success)throw Error(res.message || '操作失败'); return res.data}
  const load=async()=>{
    const next=check(await api.memeReview('overview'))
    setData(next)
    if(!initialized.current){
      initialized.current=true
      if(next.draft){setProposal(next.draft.payload.proposal);setDraftRevision(next.draft.revision)}
      else setDraftRevision(next.draft_revision || 0)
    }
    return next
  }
  const loadSeeds=async()=>{
    const seed=check(await api.getMemeSeedWords())
    setSeedText(seed.words.join('\n'));setSeedVersion(seed.version);setSeedLinks(seed.links || {})
    setBlockedSeeds(seed.blocked_names || [])
  }
  useEffect(()=>{
    let alive=true
    Promise.all([load(),loadSeeds()]).catch(e=>{if(alive)setError(e.message)})
    const timer=setInterval(()=>load().catch(e=>{if(alive)setError(e.message)}),60000)
    return()=>{alive=false;clearInterval(timer)}
  },[])
  const run=async fn=>{
    setBusy(true);setError('');setMessage('')
    try{await fn()}catch(e){setError(e.message)}finally{setBusy(false)}
  }
  const change=next=>{setProposal(next);setPreview(null);setUndo(null);requestId.current=null;setMessage('')}
  const stage=edit=>change({...proposal,adjustments:[...proposal.adjustments.filter(a=>a.board!==edit.board || a.meme_id!==edit.meme_id),edit]})
  const dictionaryEdit=edit=>change({...proposal,dictionary:[...proposal.dictionary,edit]})
  const count=proposal.adjustments.length+proposal.dictionary.length
  const dictionary=preview?.dictionary || data?.dictionary || []
  const displayName=id=>dictionary.find(r=>r.id===id)?.name || id
  const rows=(preview?.boards || data?.preview?.boards || {})[board] || []
  const candidates=data?.preview?.candidates?.[board] || []
  const list=[...rows,...candidates.filter(c=>!rows.some(r=>r.meme_id===c.meme_id))].filter(r=>nameOf(r).includes(query))
  const seeds=wordsOf(seedText)
  const seedConflicts=seeds.filter(word=>blockedSeeds.some(blocked=>blocked.normalize('NFKC').toLowerCase()===word.normalize('NFKC').toLowerCase()))
  const publish=()=>run(async()=>{
    requestId.current ||= crypto.randomUUID()
    check(await api.memeReview('publish','POST',{proposal,token:preview.token,request_id:requestId.current}))
    change(empty());const next=await load();setDraftRevision(next.draft_revision || 0);setMessage('榜单调整已发布，人工调整有效期为 24 小时')
    window.dispatchEvent(new Event('kichu:word-rules-changed'))
  })
  const inspect=entry=>run(async()=>{
    const result=check(await api.memeReview(`evidence?board=${board}&meme_id=${encodeURIComponent(entry.meme_id)}`))
    setEvidence({...result,name:nameOf(entry),meme_id:entry.meme_id,board})
  })
  const previewUndo=(operation,scope)=>run(async()=>{
    const result=check(await api.memeReview('undo-preview','POST',{operation,board:scope}))
    setUndo({...result,operation,board:scope})
  })

  return <section className="space-y-4" aria-label="梗库审核中心">
    <header className="bg-white border rounded-2xl p-5 space-y-2">
      <h2 className="text-xl font-bold">梗库审核中心</h2>
      <p className="text-sm text-slate-500">平时自动更新，每天集中审核。隐藏、补录和调序发布后生效 24 小时。</p>
      <div className="flex flex-wrap gap-3 text-xs text-slate-500">
        <span>最新期次：{data?.last_run || '等待完整采集'}</span>
        <span>上次审核：{data?.reviewed_run || '尚未审核'}</span>
        <span>{data?.needs_review?'有新一期待审核':'暂无新期次'}</span>
        {data?.mode==='shadow' && <strong className="text-amber-700">影子验证：调整暂不影响公开榜单</strong>}
      </div>
      {onRules && <button className={button} onClick={onRules}>打开词汇规则中心</button>}
    </header>
    <nav className="flex flex-wrap gap-2" aria-label="审核管理">
      {tabs.map(([id,title])=><button key={id} className={`${button} ${tab===id?'!bg-sky-100 !border-sky-400':''}`} onClick={()=>setTab(id)}>{title}</button>)}
    </nav>
    {error && <div role="alert" className="bg-red-50 text-red-800 rounded-lg p-3 break-words">{error}。修改已保留；如版本有变化，请刷新后重新预览。</div>}
    {message && <p role="status" className="bg-emerald-50 text-emerald-800 rounded-lg p-3">{message}</p>}
    {!data && <p>加载审核数据…</p>}

    {tab==='today' && <div className="space-y-3">
      {!!data?.suspected_aliases?.length && <details className="bg-amber-50 border border-amber-200 rounded-xl p-3"><summary className="cursor-pointer text-sm">{data.suspected_aliases.length} 组词条证据高度重叠，待人工确认</summary>{data.suspected_aliases.map((pair,i)=><p key={i} className="text-sm mt-2">{displayName(pair.source)} / {displayName(pair.target)} · 共用 {pair.shared} 个 BV <button className="text-sky-700 underline" onClick={()=>{setMergeSource(pair.source);setMergeTarget(pair.target);setTab('dictionary')}}>检查是否同义</button></p>)}</details>}
      <div className="flex flex-wrap gap-2">
        {Object.entries(labels).map(([id,label])=><button key={id} className={`${button} ${board===id?'!bg-sky-100':''}`} onClick={()=>setBoard(id)}>{label}</button>)}
        <input className={field} aria-label="搜索候选词" placeholder="搜索本期候选词" value={query} onChange={e=>setQuery(e.target.value)}/>
        <button className={button} disabled={busy} onClick={()=>run(load)}>刷新本期数据</button>
      </div>
      {data?.source_status?.[board] && data.source_status[board]!=='complete' && <p className="text-amber-700 text-sm">本期来源不完整，继续使用上次有效结果。</p>}
      <p className="text-xs text-slate-500">数据时间：{date(data?.preview?.source_times?.[board])} · 每个调整只作用于当前选择的库</p>
      {!!data?.recent_runs?.length && <details className="bg-white border rounded-xl p-3"><summary className="text-sm cursor-pointer">最近 {data.recent_runs.length} 期采集记录</summary>{data.recent_runs.map(run=><p key={run.id} className="text-xs mt-2">{run.id} · {date(run.finished_at)} · {Object.entries(run.boards).map(([b,status])=>`${labels[b]} ${status.count}项${status.complete?'':'（保留上期）'}${status.evidence_complete?'':' · 证据不完整'}`).join('；')}</p>)}</details>}
      {list.length===0 && <p className="bg-white border rounded-xl p-6 text-slate-500">本期暂无候选词。可先在梗词典登记，再人工补录。</p>}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        {list.slice(0,100).map(entry=><article key={entry.meme_id} className="bg-white border rounded-xl p-4 space-y-3">
          <div className="flex justify-between gap-2"><h3 className="font-bold break-words">{nameOf(entry)}</h3><span className="text-xs shrink-0 text-slate-500">{rows.some(r=>r.meme_id===entry.meme_id)?'榜内':'榜外候选'}</span></div>
          <p className="text-xs text-slate-500">{entry.video_count ?? '—'} 个视频 · 热度 {entry.heat?.toLocaleString() ?? '—'}{entry.manual?' · 人工收录':''}</p>
          <div className="flex flex-wrap gap-2">
            <button className={button} aria-label={`隐藏 ${nameOf(entry)}`} onClick={()=>stage({board,meme_id:entry.meme_id,action:'hide'})}>隐藏</button>
            <button className={button} aria-label={`补录 ${nameOf(entry)}`} onClick={()=>stage({board,meme_id:entry.meme_id,action:'add'})}>补录</button>
            <label className="text-xs flex items-center gap-1">目标位置<input className={`${field} w-20`} type="number" min="1" max={board==='hot_memes'?30:10} aria-label={`${nameOf(entry)}目标位置`}
              value={proposal.adjustments.find(a=>a.board===board&&a.meme_id===entry.meme_id)?.position || ''}
              onChange={e=>stage({board,meme_id:entry.meme_id,action:rows.some(r=>r.meme_id===entry.meme_id)?'position':'add',position:e.target.value?Number(e.target.value):null})}/></label>
            <button className={button} onClick={()=>inspect(entry)}>查看 BV 证据</button>
            <button className={button} onClick={()=>{setSeedCandidate(entry.meme_id);setSeedSearch(nameOf(entry));setTab('seeds')}}>加入采集种子词</button>
          </div>
        </article>)}
      </div>
      {list.length>100 && <p>共 {list.length} 项，当前展示前 100 项；可搜索定位。</p>}
      {evidence && <aside className="bg-white border rounded-xl p-4 space-y-2"><div className="flex justify-between"><h3>{evidence.name} · {evidence.total} 条证据</h3><button className={button} onClick={()=>setEvidence(null)}>关闭证据</button></div>
        {evidence.items?.map((e,i)=><p key={i} className="text-sm break-words"><a className="text-sky-700 underline" href={`https://www.bilibili.com/video/${encodeURIComponent(e.bvid)}`} target="_blank" rel="noreferrer">{e.bvid}</a> · {e.raw_term} · {e.source==='tag'?'标签':'标题'} · {e.video?.title}</p>)}
        {evidence.next_offset != null && <button className={button} disabled={busy} onClick={()=>run(async()=>{const next=check(await api.memeReview(`evidence?board=${evidence.board}&meme_id=${encodeURIComponent(evidence.meme_id)}&offset=${evidence.next_offset}`));setEvidence({...evidence,...next,items:[...evidence.items,...next.items]})})}>加载更多证据</button>}
      </aside>}
    </div>}

    {tab==='adjustments' && <div className="space-y-3">
      {(data?.adjustments || []).map((a,i)=><div key={i} className="bg-white border rounded-xl p-4 flex flex-wrap gap-3 items-center">
        <strong>{displayName(a.meme_id)}</strong><span>{labels[a.board]} · {actions[a.action]}{a.position?` · 第 ${a.position} 位`:''}</span>
        <span className="text-xs text-slate-500">{a.expires_at*1000<=Date.now()?'已到期':'到期'}：{date(a.expires_at)}</span>
        <button className={button} onClick={()=>stage({board:a.board,meme_id:a.meme_id,action:'revoke'})}>撤销调整</button>
        <button className={button} onClick={()=>stage({board:a.board,meme_id:a.meme_id,action:a.action,position:a.position})}>续期 24 小时</button>
      </div>)}
      {!data?.adjustments?.length && <p>暂无人工调整，榜单随采集自动更新。</p>}
      {data?.last_manual && <button className={button} disabled={busy} onClick={()=>previewUndo(data.last_manual)}>预览撤销最近一次发布</button>}
      {Object.entries(data?.last_boards || {}).map(([b,operation])=><button key={b} className={button} disabled={busy} onClick={()=>previewUndo(operation,b)}>预览撤销{labels[b]}调整</button>)}
      {data?.last_dictionary && <button className={button} disabled={busy} onClick={()=>previewUndo(data.last_dictionary,'dictionary')}>预览撤销最近词典操作</button>}
      {undo && <div className="border rounded-xl p-4 space-y-2"><p>撤销后：{Object.entries(undo.boards).map(([b,items])=>`${labels[b]} ${items.length} 项`).join('，')}。原有调整不会延长到期时间。</p>
        <button className={button} disabled={busy} onClick={()=>run(async()=>{check(await api.memeReview('undo','POST',{operation:undo.operation || data.last_manual,board:undo.board,token:undo.token,request_id:crypto.randomUUID()}));setUndo(null);await load();setMessage('已撤销选中的调整')})}>确认撤销</button></div>}
      <button className={button} disabled={busy} onClick={()=>run(async()=>setCleanup(check(await api.memeReview('cleanup-preview'))))}>查看过期数据清理预估</button>
      {cleanup && <div className="bg-white border rounded-xl p-4"><h3 className="font-semibold">清理统计 · 仅预览</h3><p className="text-sm">草稿 {cleanup.eligible?.drafts} · 期次证据 {cleanup.eligible?.runs} · 发布历史 {cleanup.eligible?.publications} · 操作记录 {cleanup.eligible?.operations}</p><p className="text-xs text-slate-500">受保护期次 {cleanup.protected_runs} 个。当前版本、回滚版本和有效引用继续保留。</p></div>}
    </div>}

    {tab==='dictionary' && <div className="space-y-4">
      <div className="bg-white border rounded-xl p-4 space-y-3"><h3 className="font-semibold">{editing?'编辑主名与别名':'登记新梗'}</h3>
        <div className="flex flex-wrap gap-2"><input className={field} aria-label="梗主名" placeholder="主名" value={editName} onChange={e=>setEditName(e.target.value)}/><input className={`${field} flex-1`} aria-label="梗别名" placeholder="别名，用逗号分隔" value={editAliases} onChange={e=>setEditAliases(e.target.value)}/>
          <button className={button} disabled={!editName.trim()} onClick={()=>{dictionaryEdit({action:editing?'edit':'register',...(editing?{id:editing}:{}),name:editName.trim(),aliases:wordsOf(editAliases)});setEditing(null);setEditName('');setEditAliases('')}}>加入待发布</button></div>
        <p className="text-xs text-slate-500">拆分叫法时，先从原梗移除该别名，再登记新梗，统一预览后发布。</p>
      </div>
      <div className="bg-white border rounded-xl p-4 space-y-3"><h3 className="font-semibold">合并不同叫法</h3><div className="flex flex-wrap gap-2">
        <select className={`${field} max-w-full`} aria-label="待合并词条" value={mergeSource} onChange={e=>setMergeSource(e.target.value)}><option value="">选择待合并词条</option>{dictionary.map(r=><option key={r.id} value={r.id}>{r.name}</option>)}</select>
        <span className="self-center">合并到</span><select className={`${field} max-w-full`} aria-label="保留词条" value={mergeTarget} onChange={e=>setMergeTarget(e.target.value)}><option value="">选择保留的主名</option>{dictionary.map(r=><option key={r.id} value={r.id}>{r.name}</option>)}</select>
        <button className={button} disabled={!mergeSource||!mergeTarget||mergeSource===mergeTarget} onClick={()=>dictionaryEdit({action:'merge',source:mergeSource,target:mergeTarget})}>加入合并预览</button></div><p className="text-xs text-slate-500">按 BV 去重重算两库；采集搜索词保持原样。</p></div>
      <input className={field} aria-label="搜索梗词典" placeholder="搜索主名或别名" value={query} onChange={e=>setQuery(e.target.value)}/>
      {dictionary.filter(r=>[r.name,...r.aliases].some(s=>s.includes(query))).slice(0,100).map(r=><div key={r.id} className="bg-white border rounded-xl p-4 flex flex-wrap gap-3 items-center"><strong>{r.name}</strong><span className="text-xs text-slate-500 break-all">{r.aliases.filter(a=>a!==r.name).join(' / ') || '无其他别名'}</span><button className={button} onClick={()=>{setEditing(r.id);setEditName(r.name);setEditAliases(r.aliases.join('，'))}}>编辑</button><input className={field} aria-label={`${r.name}关联BV`} placeholder="关联已采集 BV（选填，逗号分隔）" value={manualBvids[r.id] || ''} onChange={e=>setManualBvids({...manualBvids,[r.id]:e.target.value})}/><button className={button} onClick={()=>stage({board,meme_id:r.id,action:'add',...(manualBvids[r.id]?.trim()?{bvids:wordsOf(manualBvids[r.id])}:{})})}>补录到{labels[board]}</button><button className={button} onClick={()=>{setSeedCandidate(r.id);setSeedSearch(r.name);setTab('seeds')}}>加入采集种子词</button></div>)}
    </div>}

    {tab==='seeds' && <div className="bg-white border rounded-xl p-5 space-y-4">
      <h3 className="font-semibold">主动采集搜索词</h3><p className="text-sm text-slate-500">下次全量抓取生效。移除搜索词后，仍可通过标签或标题自然发现该梗。别名合并不会自动修改搜索词。</p>
      {seedConflicts.length>0 && <p className="rounded-lg bg-amber-50 text-amber-800 p-3 text-sm">{seedConflicts.join('、')} 命中停用规则：仍会主动搜索，公开两库会隐藏该梗。可在词汇规则中心检查。</p>}
      {seedCandidate && <div className="border border-sky-200 bg-sky-50 p-3 rounded-lg flex flex-wrap gap-2"><input className={field} aria-label="确认实际搜索词" value={seedSearch} onChange={e=>setSeedSearch(e.target.value)}/><button className={button} disabled={!seedSearch.trim()} onClick={()=>{const word=seedSearch.trim();setSeedText([...new Set([...seeds,word])].join('\n'));setSeedLinks({...seedLinks,[word]:seedCandidate});setSeedCandidate(null)}}>确认加入待保存</button><button className={button} onClick={()=>setSeedCandidate(null)}>取消</button></div>}
      <label className="block text-sm">采集搜索词<textarea aria-label="采集搜索词" className={`${field} block w-full mt-2 h-40`} value={seedText} onChange={e=>setSeedText(e.target.value)} placeholder="每行一个搜索词，清空后停止主动搜索"/></label>
      {seeds.map(word=><label className="flex flex-wrap gap-2 items-center text-sm" key={word}><span className="break-words">{word}</span><select className={`${field} max-w-full`} aria-label={`${word}关联词条`} value={seedLinks[word] || ''} onChange={e=>setSeedLinks({...seedLinks,[word]:e.target.value})}><option value="">不关联词典</option>{dictionary.map(r=><option key={r.id} value={r.id}>{r.name}</option>)}</select></label>)}
      <div className="flex gap-2 flex-wrap"><button className={`${button} !bg-emerald-600 !text-white`} disabled={busy||seedVersion===null} onClick={()=>run(async()=>{const links=Object.fromEntries(Object.entries(seedLinks).filter(([word,id])=>seeds.includes(word)&&id));const saved=check(await api.saveMemeSeedWords(seeds,seedVersion,links));setSeedVersion(saved.version);setMessage('已保存采集设置，下次全量抓取生效')})}>保存采集设置</button><button className={button} disabled={busy} onClick={()=>run(loadSeeds)}>重新读取采集设置</button></div>
    </div>}

    {tab!=='seeds' && <footer className="sticky bottom-0 bg-white/95 border rounded-xl p-4 shadow-sm space-y-3">
      <p className="font-semibold text-sm">待发布 {count} 项{preview?' · 预览已生成':''}</p>
      {proposal.adjustments.map((a,i)=><p className="text-xs" key={`a${i}`}>{labels[a.board]} · {displayName(a.meme_id)} · {actions[a.action]} {a.position || ''} <button className="text-red-600 underline" onClick={()=>change({...proposal,adjustments:proposal.adjustments.filter((_,j)=>i!==j)})}>移除</button></p>)}
      {proposal.dictionary.map((a,i)=><p className="text-xs" key={`d${i}`}>词典：{a.action==='merge'?`${displayName(a.source)} → ${displayName(a.target)}`:a.name} <button className="text-red-600 underline" onClick={()=>change({...proposal,dictionary:proposal.dictionary.filter((_,j)=>i!==j)})}>移除</button></p>)}
      {preview && <p className="text-xs">预览已生成</p>}
      <div className="flex flex-wrap gap-2">
        <button className={button} disabled={busy||!data} onClick={()=>run(async()=>{const saved=check(await api.memeReview('draft','PUT',{proposal,revision:draftRevision}));setDraftRevision(saved.revision);setMessage('草稿已保存，自动更新继续运行')})}>保存草稿</button>
        <button className={button} disabled={busy||!data} onClick={()=>run(async()=>{setPreview(check(await api.memeReview('preview','POST',{proposal})));requestId.current=null})}>预览调整</button>
        <button className={`${button} !bg-sky-600 !text-white`} disabled={busy||!preview} onClick={publish}>{count?'发布榜单调整':'标记本期已审核'}</button>
      </div>
    </footer>}
  </section>
}
