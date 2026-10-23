import { fireEvent, render, screen, act } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import PublicLink from './PublicLink'
import { usePublicNavigation } from './usePublicNavigation'

beforeEach(() => window.history.replaceState({}, '', '/'))
function Harness() {
  const {activeTab, navigate} = usePublicNavigation()
  return <><p>{activeTab}</p><PublicLink tabId="memes" onNavigate={navigate}>热梗</PublicLink>
    <button onClick={() => navigate('dev')}>管理</button></>
}
it('restores indexing when leaving UP observations and noindex on history return', () => {
  window.history.replaceState({}, '', '/up-trends')
  render(<Harness />)
  expect(document.querySelector('meta[name="robots"]')?.content).toBe('noindex, follow')
  fireEvent.click(screen.getByRole('link'))
  expect(document.querySelector('meta[name="robots"]')?.content).toBe('index, follow')
  act(() => { window.history.replaceState({}, '', '/up-trends'); window.dispatchEvent(new PopStateEvent('popstate')) })
  expect(document.querySelector('meta[name="robots"]')?.content).toBe('noindex, follow')
  expect(document.querySelectorAll('meta[name="robots"]')).toHaveLength(1)
})
it('opens a deep link, navigates and restores the historical page', () => {
  window.history.replaceState({}, '', '/rankings/potential')
  render(<Harness />)
  expect(screen.getByText('videos')).toBeVisible()
  expect(screen.getByRole('link')).toHaveAttribute('href', '/memes')
  fireEvent.click(screen.getByRole('link'))
  expect(window.location.pathname).toBe('/memes')
  expect(document.title).toBe('热梗 · GuichuHub')
  expect(document.querySelector('link[rel="canonical"]').href).toBe('https://guichuhub.cn/memes')
  expect(screen.getByText('memes')).toBeVisible()
  act(() => { window.history.replaceState({}, '', '/rankings/kichu'); window.dispatchEvent(new PopStateEvent('popstate')) })
  expect(screen.getByText('kichu-rank')).toBeVisible()
  fireEvent.click(screen.getByText('管理'))
  expect(screen.getByText('dev')).toBeVisible()
  expect(window.location.pathname).toBe('/rankings/kichu')
})
it.each([{ctrlKey:true}, {metaKey:true}, {shiftKey:true}, {altKey:true}, {button:1}])('preserves native modified link clicks %j', modifiers => {
  const navigate = vi.fn()
  render(<PublicLink tabId="memes" onNavigate={navigate}>热梗</PublicLink>)
  const event = new MouseEvent('click', {bubbles:true, cancelable:true, ...modifiers})
  screen.getByRole('link').dispatchEvent(event)
  expect(event.defaultPrevented).toBe(false)
  expect(navigate).not.toHaveBeenCalled()
})
it('preserves new-window links', () => {
  const navigate = vi.fn()
  render(<PublicLink tabId="memes" onNavigate={navigate} target="_blank">热梗</PublicLink>)
  fireEvent.click(screen.getByRole('link'))
  expect(navigate).not.toHaveBeenCalled()
})
