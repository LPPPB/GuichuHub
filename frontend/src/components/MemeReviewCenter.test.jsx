import {fireEvent, render, screen, waitFor, within} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {beforeEach, expect, it, vi} from 'vitest'
import MemeReviewCenter from './MemeReviewCenter'
import {api} from '../utils/api'

vi.mock('../utils/api', () => ({api: {memeReview: vi.fn(), getMemeSeedWords: vi.fn(), saveMemeSeedWords: vi.fn()}}))
beforeEach(() => {
  vi.clearAllMocks()
  api.getMemeSeedWords.mockResolvedValue({success:true,data:{words:['哈基米'],version:4,links:{}}})
  api.memeReview.mockImplementation(async path => ({success:true,data:path==='overview'?{
    mode:'shadow', dictionary:[{id:'a',name:'哈基米',aliases:[]}], adjustments:[],
    preview:{
      boards:{hot_memes:[{meme_id:'a',keyword:'哈基米',heat:100}],meme_materials:[]},
      base_boards:{hot_memes:[{meme_id:'a',keyword:'哈基米',heat:100}],meme_materials:[]},
      candidates:{
        hot_memes:[{meme_id:'b',keyword:'华强买瓜',heat:200},{meme_id:'c',keyword:'二仙桥',heat:20}],
        meme_materials:[{meme_id:'b',name:'华强买瓜',heat:40}],
      },
    },
    last_run:'one', needs_review:true, draft:null,
  }:path==='preview'?{token:'preview-one',boards:{hot_memes:[],meme_materials:[]}}:{}}))
})

it('previews a board hide before publishing and preserves it on conflict', async () => {
  const user=userEvent.setup()
  render(<MemeReviewCenter />)
  await user.click(await screen.findByRole('button',{name:'移回备选 哈基米'}))
  await user.click(screen.getByRole('button',{name:'预览调整'}))
  await screen.findByRole('button',{name:'发布榜单调整'})
  api.memeReview.mockResolvedValueOnce({success:false,conflict:true,message:'preview expired'})
  await user.click(screen.getByRole('button',{name:'发布榜单调整'}))
  expect(api.memeReview).toHaveBeenLastCalledWith('publish','POST',expect.objectContaining({
    token:'preview-one',proposal:{dictionary:[],adjustments:[{board:'hot_memes',meme_id:'a',action:'hide'}]},
  }))
  await screen.findByRole('alert')
  expect(screen.getByText(/待发布 1 项/)).toBeInTheDocument()
})

it('drops a candidate into heat order, then saves manual order for each board independently', async () => {
  const user=userEvent.setup()
  render(<MemeReviewCenter />)
  const selected=()=>screen.getByRole('region',{name:'选择区'})
  const candidates=()=>within(screen.getByRole('region',{name:'备选区'}))
  await screen.findByRole('region',{name:'选择区'})
  const transfer={setData:vi.fn(),effectAllowed:'move'}
  fireEvent.dragStart(candidates().getByLabelText('拖动 华强买瓜'),{dataTransfer:transfer})
  fireEvent.drop(selected(),{dataTransfer:transfer})
  const selectedNames=()=>within(selected()).queryAllByRole('heading',{level:4}).map(item=>item.textContent)
  expect(selectedNames()).toEqual(['华强买瓜','哈基米'])
  await user.click(within(selected()).getByRole('button',{name:'上移 哈基米'}))
  await user.click(candidates().getByRole('button',{name:'加入选择区 二仙桥'}))
  expect(selectedNames()).toEqual(['哈基米','华强买瓜','二仙桥'])

  await user.click(screen.getByRole('button',{name:'梗素材库'}))
  expect(selectedNames()).toEqual([])
  await user.click(candidates().getByRole('button',{name:'加入选择区 华强买瓜'}))
  await user.click(screen.getByRole('button',{name:'热梗库'}))
  expect(selectedNames()).toEqual(['哈基米','华强买瓜','二仙桥'])

  api.memeReview.mockResolvedValueOnce({success:true,data:{revision:1}})
  await user.click(screen.getByRole('button',{name:'保存草稿'}))
  const draft=api.memeReview.mock.lastCall[2].proposal.adjustments
  expect(draft).toEqual(expect.arrayContaining([
    {board:'hot_memes',meme_id:'a',action:'position',position:1},
    expect.objectContaining({board:'hot_memes',meme_id:'b',action:'add'}),
    expect.objectContaining({board:'meme_materials',meme_id:'b',action:'add'}),
  ]))
})

it('restores a saved hide and retains its published BV links when adding the term back', async () => {
  const load=api.memeReview.getMockImplementation()
  const overview=(await load('overview')).data
  const linked={board:'hot_memes',meme_id:'b',action:'add',bvids:['BV1234567890']}
  overview.adjustments=[{...linked,expires_at:Date.now()/1000+100}]
  overview.preview.boards.hot_memes=[
    {...overview.preview.candidates.hot_memes[0],manual:true},
    ...overview.preview.base_boards.hot_memes,
  ]
  overview.draft={revision:7,payload:{proposal:{dictionary:[],adjustments:[
    {board:'hot_memes',meme_id:'b',action:'hide'},
    {board:'hot_memes',meme_id:'a',action:'position',position:1},
  ]}}}
  api.memeReview.mockResolvedValueOnce({success:true,data:overview})
  const user=userEvent.setup()
  render(<MemeReviewCenter />)
  await user.click(await screen.findByRole('button',{name:'加入选择区 华强买瓜'}))
  const selected=screen.getByRole('region',{name:'选择区'})
  expect(within(selected).getAllByRole('heading',{level:4}).map(item=>item.textContent))
    .toEqual(['华强买瓜','哈基米'])
  api.memeReview.mockResolvedValueOnce({success:true,data:{revision:8}})
  await user.click(screen.getByRole('button',{name:'保存草稿'}))
  expect(api.memeReview).toHaveBeenLastCalledWith('draft','PUT',{
    revision:7,proposal:{dictionary:[],adjustments:[]},
  })
})

it('releases a stale position when a selected term takes that rank', async () => {
  const load=api.memeReview.getMockImplementation()
  const overview=(await load('overview')).data
  const rows=[...overview.preview.boards.hot_memes,overview.preview.candidates.hot_memes[1]]
  overview.preview.boards.hot_memes=rows
  overview.preview.base_boards.hot_memes=rows
  overview.adjustments=[
    {board:'hot_memes',meme_id:'off-board',action:'position',position:1,expires_at:Date.now()/1000+100},
  ]
  api.memeReview.mockResolvedValueOnce({success:true,data:overview})
  const user=userEvent.setup()
  render(<MemeReviewCenter />)
  await user.click(await screen.findByRole('button',{name:'上移 二仙桥'}))
  await user.click(screen.getByRole('button',{name:'预览调整'}))
  expect(api.memeReview.mock.lastCall[2].proposal.adjustments).toEqual(expect.arrayContaining([
    {board:'hot_memes',meme_id:'c',action:'position',position:1},
    {board:'hot_memes',meme_id:'off-board',action:'revoke'},
  ]))
})

it('keeps a compatible published position on a short board when adding a term', async () => {
  const load=api.memeReview.getMockImplementation()
  const overview=(await load('overview')).data
  overview.adjustments=[
    {board:'hot_memes',meme_id:'a',action:'position',position:10,expires_at:Date.now()/1000+100},
  ]
  api.memeReview.mockResolvedValueOnce({success:true,data:overview})
  const user=userEvent.setup()
  render(<MemeReviewCenter />)
  await user.click(await screen.findByRole('button',{name:'加入选择区 华强买瓜'}))
  await user.click(screen.getByRole('button',{name:'预览调整'}))
  expect(api.memeReview.mock.lastCall[2].proposal.adjustments).toEqual([
    {board:'hot_memes',meme_id:'b',action:'add'},
  ])
})

it('saves seed settings separately with the original version and explicit empty list', async () => {
  const user=userEvent.setup()
  api.saveMemeSeedWords.mockResolvedValue({success:true,data:{words:[],version:5,links:{}}})
  render(<MemeReviewCenter initialTab="seeds" />)
  const input=await screen.findByLabelText('采集搜索词')
  await waitFor(()=>expect(input).toHaveValue('哈基米'))
  await user.clear(input)
  await user.click(screen.getByRole('button',{name:'保存采集设置'}))
  expect(api.saveMemeSeedWords).toHaveBeenCalledWith([],4,{})
  expect(api.memeReview.mock.calls.some(([path])=>path==='publish')).toBe(false)
})
