import { describe, expect, it } from 'vitest'
import { PUBLIC_ROUTES, resolvePublicPath } from './publicRoutes'

describe('public destinations', () => {
  it.each([
    ['/', 'dashboard'], ['/rankings/kichu', 'kichu-rank'], ['/memes', 'memes'],
    ['/rankings/potential', 'videos'], ['/meme-materials', 'meme-materials'],
    ['/bgm', 'songs'], ['/materials', 'materials'], ['/insights/discussion', 'danmaku'], ['/up-trends', 'up-trends'],
  ])('opens %s as %s', (path, tabId) => {
    expect(resolvePublicPath(path).route.tabId).toBe(tabId)
  })
  it('normalizes only known trailing-slash pages', () => {
    expect(resolvePublicPath('/rankings/kichu/')).toEqual({kind: 'redirect', location: '/rankings/kichu'})
    for (const path of ['/unknown', '/dev', '//memes', '/rankings%2fkichu', '/memes//', '/%6demes']) {
      expect(resolvePublicPath(path).kind).toBe('not-found')
    }
    expect(PUBLIC_ROUTES).toHaveLength(9)
  })
})
