import {render, screen, waitFor} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {beforeEach, expect, it, vi} from 'vitest'
import DevPanel from './DevPanel'
import {api} from '../utils/api'

vi.mock('../utils/api', () => ({api: {
  getMemeStopwords: vi.fn(), getMemeSeedWords: vi.fn(), getTagFilters: vi.fn(),
  getDanmakuFilters: vi.fn(), getWordRulesOverview: vi.fn(), saveMemeStopwords: vi.fn(),
}}))
beforeEach(() => {
  api.getMemeStopwords.mockResolvedValue({success:true,data:{categories:{'人工屏蔽':[]}}})
  api.getMemeSeedWords.mockResolvedValue({success:true,data:{words:[]}})
  api.getTagFilters.mockResolvedValue({success:true,data:{}})
  api.getDanmakuFilters.mockResolvedValue({success:true,data:{}})
  api.getWordRulesOverview.mockResolvedValue({success:true,data:{}})
})

it.each([true,false])('only a successful blacklist save notifies the dashboard: %s', async success => {
  const listener=vi.fn()
  window.addEventListener('kichu:word-rules-changed',listener)
  try {
    api.saveMemeStopwords.mockResolvedValue({success,message:success?'已立即生效':'保存失败'})
    const user=userEvent.setup()
    render(<DevPanel />)
    await user.click(await screen.findByRole('button',{name:/素材\/热梗/}))
    await user.type(screen.getByPlaceholderText('添加词（支持空格/逗号分隔多个）'),'哈基米')
    await user.click(screen.getByTitle('添加'))
    await user.click(screen.getByRole('button',{name:'保存规则'}))
    await waitFor(()=>expect(api.saveMemeStopwords).toHaveBeenCalledWith({'人工屏蔽':['哈基米']}))
    await screen.findByText(success?'已立即生效':'保存失败')
    expect(listener).toHaveBeenCalledTimes(success?1:0)
  } finally { window.removeEventListener('kichu:word-rules-changed',listener) }
})
