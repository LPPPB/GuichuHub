import { routeForTab } from '../routing/publicRoutes.js'

export const MAX_BOOTSTRAP_BYTES = 2 * 1024 * 1024
const plain = value => value && typeof value === 'object' && !Array.isArray(value)
export function validateBootstrap(value) {
  if (!plain(value) || value.schema_version !== 1 || !routeForTab(value.tab_id) ||
      !/^[a-zA-Z0-9_-]{1,128}$/.test(value.build_id || '') || !plain(value.sections) || !plain(value.confirmed_at) ||
      !Number.isInteger(value.render_year) || value.render_year < 2000 || value.render_year > 9999) return null
  try {
    if (new TextEncoder().encode(JSON.stringify(value)).length > MAX_BOOTSTRAP_BYTES) return null
    for (const [tab, section] of Object.entries(value.sections)) {
      if (!routeForTab(tab) || !plain(section) || !['ready', 'empty', 'unavailable'].includes(section.status) || !plain(section.data) ||
          (section.status !== 'unavailable' && (typeof section.content_version !== 'string' || section.content_version.length > 128)) ||
          (section.source_updated_at !== null && (!Number.isFinite(section.source_updated_at) || section.source_updated_at < 0))) return null
    }
    return value
  } catch { return null }
}
export function serializeBootstrap(value) {
  if (!validateBootstrap(value)) throw new Error('Invalid public bootstrap')
  return JSON.stringify(value).replace(/</g, '\\u003c').replace(/\u2028/g, '\\u2028').replace(/\u2029/g, '\\u2029')
}
export function initialProps(bootstrap) {
  const initialData = {}
  for (const section of Object.values(bootstrap.sections)) {
    if (section.status !== 'unavailable') Object.assign(initialData, section.data.dashboard || section.data)
  }
  return {initialTab: bootstrap.tab_id, initialData, initialAux: bootstrap, renderYear: bootstrap.render_year}
}
