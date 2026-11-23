import {useRef, useState} from 'react'
import {ArrowDown, ArrowUp, GripVertical, Minus, MoreHorizontal, Plus} from 'lucide-react'
import {byHeat, nameOf, reviewLimits} from '../utils/memeReviewSelection'

const control = 'inline-flex min-h-8 min-w-8 items-center justify-center rounded-md text-slate-600 hover:bg-sky-100 hover:text-sky-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-600 disabled:opacity-30'
const utility = 'rounded-md border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-40'

export default function MemeReviewSelection({selection, onChange, onInspect, onSeed, disabled}) {
  const {board, selected, candidates, effective}=selection
  const limit=reviewLimits[board]
  const [query,setQuery]=useState('')
  const [target,setTarget]=useState(null)
  const drag=useRef(null)
  const filtered=candidates.filter(row=>nameOf(row).toLowerCase().includes(query.trim().toLowerCase()))

  function add(entry) {
    const next=selected.slice(0,limit-1)
    if (next.some(row=>effective.get(row.meme_id)?.position)) {
      const index=next.findIndex(row=>byHeat(entry,row)<0)
      next.splice(index===-1 ? next.length : index,0,entry)
    } else {
      next.push(entry)
      next.sort(byHeat)
    }
    onChange(next)
  }

  function remove(entry) {
    onChange(selected.filter(row=>row.meme_id!==entry.meme_id))
  }

  function move(entry, index) {
    const next=selected.filter(row=>row.meme_id!==entry.meme_id)
    next.splice(index,0,entry)
    if (next.some((row,i)=>row!==selected[i])) onChange(next)
  }

  function hit(node, y) {
    const zone=node?.closest?.('[data-review-zone]')
    if (!zone) return null
    const row=node.closest('[data-review-index]') || (zone.dataset.reviewZone==='selected'
      ? [...zone.querySelectorAll('[data-review-index]')].find(item=>y<=item.getBoundingClientRect().bottom)
      : null)
    const rect=row?.getBoundingClientRect()
    return {
      zone:zone.dataset.reviewZone,
      index:row ? Number(row.dataset.reviewIndex) : null,
      after:rect && y>rect.top+rect.height/2,
    }
  }

  function finish(destination) {
    const source=drag.current
    drag.current=null
    setTarget(null)
    if (disabled || !source || !destination) return
    if (source.zone==='candidates' && destination.zone==='selected') {
      add(source.entry)
    } else if (source.zone==='selected' && destination.zone==='candidates') {
      remove(source.entry)
    } else if (source.zone==='selected' && destination.zone==='selected') {
      const oldIndex=selected.findIndex(row=>row.meme_id===source.entry.meme_id)
      if (oldIndex===-1) return
      if (destination.index===oldIndex) return
      const slot=destination.index==null ? selected.length : destination.index+Number(destination.after)
      move(source.entry,slot-Number(slot>oldIndex))
    }
  }

  function showTarget(destination) {
    setTarget(destination?.zone==='selected' || drag.current?.zone==='selected' ? destination : null)
  }

  function dragHandle(entry, zone) {
    const label=`拖动 ${nameOf(entry)}`
    return <span
      aria-label={label}
      title={label}
      className="flex h-9 w-8 shrink-0 touch-none select-none items-center justify-center rounded-md text-slate-500 hover:bg-slate-100 aria-disabled:opacity-40"
      style={{cursor:disabled ? 'default' : 'grab'}}
      aria-disabled={disabled}
      draggable={!disabled}
      onDragStart={event=>{
        drag.current={entry,zone}
        event.dataTransfer.effectAllowed='move'
        event.dataTransfer.setData('text/plain',nameOf(entry))
      }}
      onDragEnd={()=>finish(null)}
      onPointerDown={event=>{
        if (disabled || event.pointerType==='mouse') return
        event.preventDefault()
        drag.current={entry,zone}
        event.currentTarget.setPointerCapture(event.pointerId)
      }}
      onPointerMove={event=>{
        if (event.pointerType!=='mouse' && drag.current) {
          showTarget(hit(document.elementFromPoint(event.clientX,event.clientY),event.clientY))
        }
      }}
      onPointerUp={event=>{
        if (event.pointerType!=='mouse' && drag.current) {
          finish(hit(document.elementFromPoint(event.clientX,event.clientY),event.clientY))
        }
      }}
      onPointerCancel={()=>finish(null)}
    ><GripVertical size={16} aria-hidden="true"/></span>
  }

  function dropZone(zone) {
    return {
      'data-review-zone':zone,
      onDragOver:event=>{
        if (!drag.current) return
        event.preventDefault()
        event.dataTransfer.dropEffect='move'
        showTarget(hit(event.target,event.clientY))
      },
      onDragLeave:event=>{
        if (!event.currentTarget.contains(event.relatedTarget)) setTarget(null)
      },
      onDrop:event=>{
        if (!drag.current) return
        event.preventDefault()
        finish(hit(event.target,event.clientY))
      },
    }
  }

  function entryDetails(entry) {
    return <details className="shrink-0">
      <summary className={`${control} absolute right-1.5 top-2 cursor-pointer list-none [&::-webkit-details-marker]:hidden`} aria-label={`${nameOf(entry)}的更多操作`}>
        <MoreHorizontal size={16} aria-hidden="true"/>
      </summary>
      <div className="mt-1 flex flex-wrap gap-1 pl-8">
        <button className={utility} disabled={disabled} onClick={()=>onInspect(entry)}>查看 BV 证据</button>
        <button className={utility} disabled={disabled} onClick={()=>onSeed(entry)}>加入采集种子词</button>
      </div>
    </details>
  }

  function showEntry(entry, index) {
    const chosen=index!==undefined
    const name=nameOf(entry)
    const activeRow=chosen && target?.zone==='selected' && target.index===index
    return <li
      key={entry.meme_id}
      data-review-index={index}
      className={`relative min-w-0 rounded-lg border bg-white p-1.5 ${activeRow
        ? target.after ? 'border-slate-200 border-b-sky-500 shadow-[0_2px_0_#0ea5e9]' : 'border-slate-200 border-t-sky-500 shadow-[0_-2px_0_#0ea5e9]'
        : 'border-slate-200'}`}
    >
      <div className="flex min-w-0 items-center gap-1 pr-8">
        {dragHandle(entry,chosen ? 'selected' : 'candidates')}
        {chosen && <span className="w-5 shrink-0 text-center text-xs tabular-nums text-slate-500">{index+1}</span>}
        <div className="min-w-0 flex-1">
          <h4 className="break-words text-sm font-semibold leading-snug text-slate-900">{name}</h4>
          <p className="mt-0.5 text-xs tabular-nums text-slate-500">
            {entry.heat==null ? '暂无热度' : `热度 ${entry.heat.toLocaleString('zh-CN')}`}
            {entry.video_count!=null && ` · ${entry.video_count} 个视频`}
          </p>
        </div>
        {chosen ? <>
          <button className={control} disabled={disabled || index===0} aria-label={`上移 ${name}`} title="上移" onClick={()=>move(entry,index-1)}><ArrowUp size={15}/></button>
          <button className={control} disabled={disabled || index===selected.length-1} aria-label={`下移 ${name}`} title="下移" onClick={()=>move(entry,index+1)}><ArrowDown size={15}/></button>
          <button className={control} disabled={disabled} aria-label={`移回备选 ${name}`} title="移回备选" onClick={()=>remove(entry)}><Minus size={16}/></button>
        </> : <button className={control} disabled={disabled} aria-label={`加入选择区 ${name}`} title="加入选择区" onClick={()=>add(entry)}><Plus size={16}/></button>}
      </div>
      {entryDetails(entry)}
    </li>
  }

  return <div className="grid items-start gap-4 lg:grid-cols-[minmax(21rem,2fr)_minmax(0,3fr)]">
    <section aria-label="选择区" {...dropZone('selected')}
      className={`min-w-0 space-y-3 rounded-xl border p-3 sm:p-4 ${target?.zone==='selected' ? 'border-sky-500 bg-sky-100' : 'border-sky-200 bg-sky-50/70'}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-semibold text-slate-900">选择区 <span className="ml-1 text-xs font-medium tabular-nums text-slate-600">{selected.length} / {limit}</span></h3>
        <button className={utility} disabled={disabled || selected.length<2 || selected.every((row,i)=>!i || byHeat(selected[i-1],row)<=0)} onClick={()=>onChange([...selected].sort(byHeat))}>按热度排序</button>
      </div>
      <p className="text-xs text-slate-600">{selected.length===limit ? '已满额，加入新词会将最后一项移回备选。' : '加入时按热度插入，可拖动已选词调序。'}</p>
      {selected.length ? <ol className="max-h-64 space-y-1.5 overflow-y-auto p-0.5 lg:max-h-[min(61vh,44rem)]">{selected.map(showEntry)}</ol>
        : <p className="rounded-lg border border-dashed border-sky-300 bg-white/70 px-3 py-6 text-center text-sm text-slate-600">将备选词拖到这里，或点按「＋」加入。</p>}
    </section>
    <section aria-label="备选区" {...dropZone('candidates')}
      className={`min-w-0 space-y-3 rounded-xl border p-3 sm:p-4 ${target?.zone==='candidates' ? 'border-sky-500 bg-sky-50' : 'border-slate-200 bg-white'}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-semibold text-slate-900">备选区 <span className="ml-1 text-xs font-medium tabular-nums text-slate-600">{candidates.length} 词</span></h3>
        <input className="min-w-0 max-w-full rounded-lg border border-slate-300 px-2.5 py-1.5 text-sm" aria-label="搜索备选词" placeholder="搜索备选词" value={query} onChange={event=>setQuery(event.target.value)}/>
      </div>
      {filtered.length ? <ul className="grid max-h-[min(50vh,27rem)] grid-cols-1 gap-1.5 overflow-y-auto p-0.5 sm:grid-cols-2 lg:max-h-[min(61vh,44rem)]">{filtered.slice(0,100).map(entry=>showEntry(entry))}</ul>
        : <p className="rounded-lg bg-slate-50 px-3 py-6 text-center text-sm text-slate-600">{query.trim() ? '未找到匹配的备选词' : '本期暂无备选词'}</p>}
      {filtered.length>100 && <p className="text-xs text-slate-600">显示前 100 项，可搜索其余词条。</p>}
    </section>
  </div>
}
