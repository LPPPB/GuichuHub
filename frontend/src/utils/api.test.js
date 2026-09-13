import { beforeEach, describe, expect, it, vi } from 'vitest'


function jsonResponse(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: async () => JSON.stringify(body),
  }
}


describe('cookie-backed API requests', () => {
  beforeEach(() => {
    vi.resetModules()
    vi.restoreAllMocks()
    localStorage.clear()
  })

  it('uses same-origin credentials without reading or sending a legacy session token', async () => {
    localStorage.setItem('kichu_session_token', 'legacy-browser-secret')
    const fetchSpy = vi.fn().mockResolvedValue(jsonResponse({
      success: true,
      data: { admin: false, via: 'session', user: { mid: 42 } },
    }))
    vi.stubGlobal('fetch', fetchSpy)
    const { api } = await import('./api.js')

    await api.getAuthMe()

    expect(localStorage.getItem('kichu_session_token')).toBeNull()
    expect(fetchSpy).toHaveBeenCalledTimes(1)
    const [, options] = fetchSpy.mock.calls[0]
    expect(options.credentials).toBe('same-origin')
    expect(options.headers).not.toHaveProperty('X-Session-Token')
  })

  it('does not persist a session token even if an older server returns one', async () => {
    const fetchSpy = vi.fn().mockResolvedValue(jsonResponse({
      success: true,
      status: 'success',
      session_token: 'server-session-secret',
      user: { mid: 42 },
    }))
    vi.stubGlobal('fetch', fetchSpy)
    const { api } = await import('./api.js')

    await api.checkLogin('qr-key')

    expect(localStorage.getItem('kichu_session_token')).toBeNull()
    const [, options] = fetchSpy.mock.calls[0]
    expect(options.credentials).toBe('same-origin')
    expect(options.headers).not.toHaveProperty('X-Session-Token')
  })

  it('uses same-origin credentials for silent write-token verification', async () => {
    localStorage.setItem('kichu_write_token', 'separate-write-token')
    const fetchSpy = vi.fn().mockResolvedValue(jsonResponse({ success: true }))
    vi.stubGlobal('fetch', fetchSpy)
    const { verifyAdminSilent } = await import('./api.js')

    expect(await verifyAdminSilent()).toBe(true)

    const [, options] = fetchSpy.mock.calls[0]
    expect(options.credentials).toBe('same-origin')
    expect(options.headers['X-Write-Token']).toBe('separate-write-token')
    expect(options.headers).not.toHaveProperty('X-Session-Token')
  })
})
