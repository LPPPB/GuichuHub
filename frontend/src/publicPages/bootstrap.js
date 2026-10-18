import { validateBootstrap } from './contract'
export function readBootstrap(document) {
  try {
    const node = document.getElementById('public-page-bootstrap')
    if (!node || node.textContent.length > 2 * 1024 * 1024) return null
    return validateBootstrap(JSON.parse(node.textContent))
  } catch { return null }
}
