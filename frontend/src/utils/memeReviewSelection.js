export const reviewLimits = {hot_memes:30, meme_materials:10}
export const nameOf = row => row.keyword || row.name || row.meme_id
export const byHeat = (a,b) => (b.heat ?? -1) - (a.heat ?? -1)

const byId = rows => new Map(rows.map(row=>[row.meme_id,row]))

function effectiveAdjustments(active, pending) {
  const edits=new Map(active)
  for (const [id,edit] of pending) {
    edits.delete(id)
    if (edit.action!=='revoke') edits.set(id,edit)
  }
  return edits
}

// Match the review service's slot assignment when reconstructing an existing draft.
function rankSelection(board, base, available, edits) {
  const rows=new Map(base), added=new Set(), positions=new Map(), pinned=new Set()
  for (const [id,edit] of edits) {
    if (edit.action==='hide') rows.delete(id)
    if (edit.action==='add' && !rows.has(id) && available.has(id)) {
      rows.set(id,available.get(id))
      added.add(id)
    }
    if (edit.position && rows.has(id)) {
      positions.set(edit.position,id)
      pinned.add(id)
    }
  }
  const unpinned=[...rows.keys()].filter(id=>!pinned.has(id))
  const queue=[...unpinned.filter(id=>added.has(id)),...unpinned.filter(id=>!added.has(id))]
  const ranked=[]
  for (let position=1;position<=reviewLimits[board];position++) {
    const id=positions.get(position) ?? queue.shift()
    if (id!=null) ranked.push(available.get(id))
  }
  return ranked
}

export function reviewSelection(board, data, proposal) {
  const current=data?.preview?.boards?.[board] || []
  const base=byId(data?.preview?.base_boards?.[board] || current.filter(row=>!row.manual))
  const active=byId((data?.adjustments || []).filter(edit=>edit.board===board && edit.expires_at*1000>Date.now()))
  const pending=byId(proposal.adjustments.filter(edit=>edit.board===board))
  const effective=effectiveAdjustments(active,pending)
  const available=byId([...(data?.preview?.candidates?.[board] || []),...base.values(),...current])
  for (const [id,edit] of effective) {
    if (edit.action==='add' && !available.has(id)) {
      const record=data?.dictionary?.find(row=>row.id===id)
      if (record) available.set(id,{meme_id:id,name:record.name,manual:true})
    }
  }
  const selected=pending.size ? rankSelection(board,base,available,effective) : current
  const selectedIds=new Set(selected.map(row=>row.meme_id))
  const candidates=[...available.values()].filter(row=>!selectedIds.has(row.meme_id)).sort(byHeat)
  return {board,base,active,pending,effective,available,selected,candidates}
}

function sameEdit(first, second) {
  return first?.action===second?.action
    && (first?.position ?? null)===(second?.position ?? null)
    && JSON.stringify(first?.bvids || [])===JSON.stringify(second?.bvids || [])
}

export function selectionAdjustments(selection, selected) {
  const {board,base,active,effective,available}=selection
  const pending=new Map(selection.pending)
  const ids=new Set(selected.map(row=>row.meme_id))

  function setEdit(id, target) {
    if (sameEdit(target,effective.get(id)) && selection.pending.has(id)) return
    if (sameEdit(target,active.get(id))) pending.delete(id)
    else pending.set(id,{board,meme_id:id,...(target || {action:'revoke'})})
  }

  for (const id of new Set([...base.keys(),...effective.keys()])) {
    if (ids.has(id)) continue
    if (base.has(id)) setEdit(id,{action:'hide'})
    else if (effective.get(id)?.action==='add') {
      setEdit(id,active.get(id)?.action==='hide' ? {action:'hide'} : null)
    }
  }

  const additions=new Map()
  for (const {meme_id:id} of selected) {
    const prior=effective.get(id)
    const published=active.get(id)
    const priorAddition=prior?.action==='add' ? prior : published?.action==='add' ? published : null
    const addition=!base.has(id) || priorAddition
      ? {action:'add',...(priorAddition?.bvids?.length ? {bvids:priorAddition.bvids} : {})}
      : null
    additions.set(id,addition)
    setEdit(id,prior?.position ? {...(addition || {action:'position'}),position:prior.position} : addition)
  }

  const rankPending=()=>rankSelection(board,base,available,effectiveAdjustments(active,pending))
  const ranked=rankPending()
  if (selected.some((row,index)=>ranked[index]?.meme_id!==row.meme_id)) {
    // Sparse positions can still give the desired order on a shorter board.
    // If the order needs changing, release displaced positions before reserving new ones.
    for (const [index,{meme_id:id}] of selected.entries()) {
      if (effective.get(id)?.position!==index+1) setEdit(id,additions.get(id))
    }
    for (const [index,{meme_id:id}] of selected.entries()) {
      if (rankPending()[index]?.meme_id!==id) {
        setEdit(id,{...(additions.get(id) || {action:'position'}),position:index+1})
      }
    }
  }

  // The service reserves old positions even when a term falls off the automatic board.
  const finalEdits=effectiveAdjustments(active,pending)
  const occupied=new Set(selected.map(row=>finalEdits.get(row.meme_id)?.position).filter(Boolean))
  for (const [id,edit] of finalEdits) {
    if (!ids.has(id) && edit.action==='position' && occupied.has(edit.position)) setEdit(id,null)
  }
  return [...pending.values()]
}
