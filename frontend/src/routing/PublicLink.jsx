import { forwardRef } from 'react'
import { routeForTab } from './publicRoutes'

const PublicLink = forwardRef(function PublicLink({tabId, onNavigate, onClick, children, ...props}, ref) {
  const route = routeForTab(tabId)
  if (!route) throw new Error('Unknown public destination')
  return <a {...props} ref={ref} href={route.path} onClick={event => {
    onClick?.(event)
    if (event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey ||
        (props.target && props.target !== '_self') || props.download != null || !onNavigate) return
    event.preventDefault()
    onNavigate(tabId)
  }}>{children}</a>
})
export default PublicLink
