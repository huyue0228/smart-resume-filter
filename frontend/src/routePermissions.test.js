import { describe, expect, it, vi } from 'vitest'
import { canAccessRoute, DEFAULT_AUTHENTICATED_PATH } from './routePermissions'

describe('route permissions', () => {
  it('keeps the resume library as the authenticated landing page', () => {
    expect(DEFAULT_AUTHENTICATED_PATH).toBe('/resumes')
  })

  it('allows a route when any configured permission is available', () => {
    const hasPermission = vi.fn((code) => code === 'attempt.view_assigned')

    expect(canAccessRoute('/resumes', hasPermission)).toBe(true)
    expect(canAccessRoute('/jobs', hasPermission)).toBe(false)
  })

  it('does not restrict menu groups without a permission entry', () => {
    expect(canAccessRoute('/data', vi.fn(() => false))).toBe(true)
  })
})
