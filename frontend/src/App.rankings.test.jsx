import {render,screen,within} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {beforeEach,afterEach,expect,it,vi} from 'vitest'
import App from './App'

vi.mock('./utils/api',()=>({verifyAdminSilent:vi.fn().mockResolvedValue(false),api:{
  getDashboard:vi.fn().mockResolvedValue({success:true,data:{
    kichu_rank:[{bvid:'BVsame',title:'双榜作品',official_rank:7,views:1000}],
    hot_videos:[{bvid:'BVsame',title:'双榜作品',official_rank:7,views:1000}],
    kichu_rank_meta:{source:'bilibili_official_ranking_v2',status:'available'},
    potential_meta:{source:'independent_discovery',status:'available'},
  }}),
  getFavorites:vi.fn().mockResolvedValue({success:true,data:[]}),
  getAuthMe:vi.fn().mockResolvedValue({success:true,data:{admin:false,user:null}}),
  getStatus:vi.fn().mockResolvedValue({success:true,data:{crawling:false}}),
  getInteractionQuality:vi.fn().mockResolvedValue({success:true,data:[]}),
  getTagHeat:vi.fn().mockResolvedValue({success:true,data:[]}),
  getRisingWords:vi.fn().mockResolvedValue({success:true,data:[]}),
  getBurstingVideos:vi.fn().mockResolvedValue({success:true,data:[]}),
}}))

beforeEach(()=>{localStorage.setItem('kb-theme','dark');vi.spyOn(window,'scrollTo').mockImplementation(()=>{})})
afterEach(()=>vi.restoreAllMocks())

it('shows official provenance and contextual ranks on home and ranking page',async()=>{
  const user=userEvent.setup()
  const {container}=render(<App />)
  expect(await screen.findByText(/哔哩哔哩官方榜/)).toBeVisible()
  expect([...container.querySelectorAll('.kb-rank')].map(n=>n.textContent)).toEqual(['7','1'])
  const section=screen.getByRole('heading',{name:'鬼畜区排行榜',exact:true}).closest('section')
  await user.click(within(section).getByRole('button',{name:'查看全部 →'}))
  expect(screen.getByText(/哔哩哔哩官方榜/)).toBeVisible()
  expect(container.querySelector('.kb-rank')).toHaveTextContent('7')
})
