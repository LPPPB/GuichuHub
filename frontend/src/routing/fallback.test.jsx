import {createContext} from 'react'
import {render,screen} from '@testing-library/react'
import {expect,it,vi} from 'vitest'
import PublicLink, * as publicLinkModule from './PublicLink'

it('keeps native navigation when the target public snapshot has not been loaded',()=>{
  const Context=publicLinkModule.PublicNavigationAvailability || createContext(()=>true)
  const navigate=vi.fn()
  render(<Context.Provider value={()=>false}><PublicLink tabId="kichu-rank" onNavigate={navigate}>鬼畜榜</PublicLink></Context.Provider>)
  const event=new MouseEvent('click',{bubbles:true,cancelable:true})
  screen.getByRole('link').dispatchEvent(event)
  expect(event.defaultPrevented).toBe(false)
  expect(navigate).not.toHaveBeenCalled()
})
