import React from 'react'
import { renderToString } from 'react-dom/server'
import { hydrateRoot } from 'react-dom/client'
import { act, within } from '@testing-library/react'
import { expect, it, vi, beforeEach } from 'vitest'
import App from '../App'
import { api } from '../utils/api'

vi.mock('../utils/api', () => ({verifyAdminSilent:vi.fn().mockResolvedValue(false),api:{
  getDashboard:vi.fn(), getFavorites:vi.fn().mockResolvedValue({success:true,data:[]}),
  getAuthMe:vi.fn().mockResolvedValue({success:true,data:{admin:false,user:null}}),
  getStatus:vi.fn().mockResolvedValue({success:true,data:{}}),
  getInteractionQuality:vi.fn().mockResolvedValue({success:true,data:[]}),
  getTagHeat:vi.fn().mockResolvedValue({success:true,data:[]}),
  getRisingWords:vi.fn().mockResolvedValue({success:true,data:[]}),
}}))
const data = {kichu_rank:[{bvid:'BV1HYp16oE8v',title:'持久公开作品',author:'公开作者',views:1000}]}
beforeEach(() => {
  localStorage.setItem('kb-theme','dark')
  api.getDashboard.mockReturnValue(new Promise(() => {}))
})
it('keeps SSR content while refreshing instead of replacing it with a spinner', async () => {
  const props={initialTab:'kichu-rank',initialData:data,renderYear:2024}
  const container=document.createElement('div')
  container.innerHTML=renderToString(<App {...props} />)
  document.body.append(container)
  const recover=vi.fn()
  let root
  await act(async () => {root=hydrateRoot(container,<App {...props} />,{onRecoverableError:recover})})
  expect(within(container).getByRole('link',{name:'持久公开作品'})).toBeVisible()
  expect(within(container).getByText('© 2024 GuichuHub')).toBeInTheDocument()
  expect(recover).not.toHaveBeenCalled()
  await act(async () => root.unmount())
  container.remove()
})
it('hydrates with saved light theme and preserves content after rejected public refresh', async () => {
  const props={initialTab:'kichu-rank',initialData:data,renderYear:2024}
  const container=document.createElement('div')
  container.innerHTML=renderToString(<App {...props} />)
  document.body.append(container)
  localStorage.setItem('kb-theme','light')
  localStorage.setItem('danmaku_blocked','["合成词"]')
  api.getDashboard.mockRejectedValue(new Error('offline'))
  const recover=vi.fn()
  let root
  await act(async () => {root=hydrateRoot(container,<App {...props} />,{onRecoverableError:recover})})
  expect(recover).not.toHaveBeenCalled()
  expect(within(container).getByRole('link',{name:'持久公开作品'})).toBeVisible()
  expect(document.documentElement).not.toHaveClass('dark')
  await act(async () => root.unmount())
  container.remove()
})
