import {render, screen, waitFor} from '@testing-library/react'
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
    preview:{boards:{hot_memes:[{meme_id:'a',keyword:'哈基米',heat:100}],meme_materials:[]},candidates:{}},
    last_run:'one', needs_review:true, draft:null,
  }:path==='preview'?{token:'preview-one',boards:{hot_memes:[],meme_materials:[]}}:{}}))
})

it('previews a board hide before publishing and preserves it on conflict', async () => {
  const user=userEvent.setup()
  render(<MemeReviewCenter />)
  await user.click(await screen.findByRole('button',{name:'隐藏 哈基米'}))
  await user.click(screen.getByRole('button',{name:'预览调整'}))
  await screen.findByText('预览已生成')
  api.memeReview.mockResolvedValueOnce({success:false,conflict:true,message:'preview expired'})
  await user.click(screen.getByRole('button',{name:'发布榜单调整'}))
  expect(api.memeReview).toHaveBeenLastCalledWith('publish','POST',expect.objectContaining({
    token:'preview-one',proposal:{dictionary:[],adjustments:[{board:'hot_memes',meme_id:'a',action:'hide'}]},
  }))
  await screen.findByRole('alert')
  expect(screen.getByText(/待发布 1 项/)).toBeInTheDocument()
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
