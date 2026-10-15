import {render,screen} from '@testing-library/react'
import {expect,it} from 'vitest'
import RankingSource from './RankingSource'

it('shows source, receipt time and failure without losing usable chart',()=>{
  render(<RankingSource meta={{source:'bilibili_official_ranking_v2',status:'available',fetched_at:1700000000,historical:true,last_attempt:{outcome:'error'}}} />)
  expect(screen.getByText(/哔哩哔哩官方榜/)).toBeVisible()
  expect(screen.getByText(/抓取于.*2023-11-15 06:13.*北京时间/)).toBeVisible()
  expect(screen.getByText(/更新失败/)).toBeVisible()
  expect(screen.getByText(/历史榜单/)).toBeVisible()
  expect(screen.queryByText(/官方更新时间/)).not.toBeInTheDocument()
})

it('distinguishes missing official from legacy source',()=>{
  const {rerender}=render(<RankingSource meta={{source:'bilibili_official_ranking_v2',status:'unavailable'}} />)
  expect(screen.getByText(/暂无官方榜数据/)).toBeVisible()
  rerender(<RankingSource />)
  expect(screen.getByText(/来源未知/)).toBeVisible()
  expect(screen.queryByText(/哔哩哔哩官方榜/)).not.toBeInTheDocument()
})

it('explains independent potential scores and stale charts',()=>{
  const {rerender}=render(<RankingSource meta={{source:'independent_discovery',status:'available'}} />)
  expect(screen.getByText(/本批相对评分/)).toBeVisible()
  rerender(<RankingSource meta={{source:'bilibili_official_ranking_v2',status:'available',stale:true}} />)
  expect(screen.getByText(/榜单已过期/)).toBeVisible()
})
