import {act, render, screen, waitFor} from '@testing-library/react'
import {beforeEach, expect, it, vi} from 'vitest'
import {api} from './utils/api'
import App from './App'

vi.mock('./utils/api',()=>({verifyAdminSilent:vi.fn().mockResolvedValue(false),api:{
  getDashboard:vi.fn(),getFavorites:vi.fn().mockResolvedValue({success:true,data:[]}),
  getAuthMe:vi.fn().mockResolvedValue({success:true,data:{admin:false,user:null}}),
  getStatus:vi.fn().mockResolvedValue({success:true,data:{crawling:false,meme_rules_version:1}}),
  getInteractionQuality:vi.fn().mockResolvedValue({success:true,data:[]}),
  getTagHeat:vi.fn().mockResolvedValue({success:true,data:[]}),
  getRisingWords:vi.fn().mockResolvedValue({success:true,data:[],meta:null}),
}}))

beforeEach(()=>vi.clearAllMocks())

it('removes an existing meme immediately after a successful rules save notification',async()=>{
  localStorage.setItem('kb-theme','light')
  vi.spyOn(window,'scrollTo').mockImplementation(()=>{})
  api.getDashboard.mockResolvedValueOnce({success:true,data:{hot_memes:[{keyword:'待屏蔽热梗',heat:100,related_videos:[]}]}})
    .mockResolvedValue({success:true,data:{hot_memes:[]}})
  render(<App />)
  await screen.findByText('待屏蔽热梗')
  act(()=>window.dispatchEvent(new Event('kichu:word-rules-changed')))
  await waitFor(()=>expect(screen.queryByText('待屏蔽热梗')).not.toBeInTheDocument())
  expect(api.getDashboard).toHaveBeenCalledTimes(2)
})

it('retries an unapplied rules revision on the next status poll after a failed refresh',async()=>{
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-10-26T00:00:00+08:00'))
  localStorage.setItem('kb-theme','light')
  api.getStatus.mockResolvedValueOnce({success:true,data:{crawling:false,meme_rules_version:1}})
    .mockResolvedValue({success:true,data:{crawling:false,meme_rules_version:2}})
  api.getDashboard.mockResolvedValueOnce({success:true,data:{hot_memes:[{keyword:'待屏蔽热梗',heat:100}]}})
    .mockResolvedValueOnce({success:false})
    .mockResolvedValue({success:true,data:{hot_memes:[]}})
  try {
    render(<App />)
    await act(async()=>{await vi.advanceTimersByTimeAsync(0)})
    expect(screen.getByText('待屏蔽热梗')).toBeInTheDocument()
    await act(async()=>{await vi.advanceTimersByTimeAsync(15000)})
    expect(api.getDashboard).toHaveBeenCalledTimes(2)
    expect(screen.getByText('待屏蔽热梗')).toBeInTheDocument()
    await act(async()=>{await vi.advanceTimersByTimeAsync(15000)})
    expect(api.getDashboard).toHaveBeenCalledTimes(3)
    expect(screen.queryByText('待屏蔽热梗')).not.toBeInTheDocument()
  } finally {vi.clearAllTimers();vi.useRealTimers()}
})
