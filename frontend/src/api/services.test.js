import { afterEach, describe, expect, it, vi } from 'vitest'
import { reportUsagePageView } from './services'

describe('reportUsagePageView', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('posts the token-authenticated event through the silent fetch path', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true })
    vi.stubGlobal('fetch', fetchMock)
    localStorage.setItem('srf_token', 'dev-token')
    const body = {
      event_id: 'fd072741-3d0a-4606-8d11-e79c496e5acc',
      session_id: '01fcffbc-472d-467a-a755-17d166744db0',
      page_key: '/analytics',
    }

    await reportUsagePageView(body)

    expect(fetchMock).toHaveBeenCalledWith('/api/analytics/usage/page-view/', {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Token dev-token',
      },
      body: JSON.stringify(body),
    })
  })
})
