import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { RoleProvider } from './RoleContext'
import { useRole } from './roleState'
import { completeW3OAuth2Login, fetchMe } from '../api/services'

vi.mock('../api/services', () => ({
  completeW3OAuth2Login: vi.fn(),
  fetchMe: vi.fn(),
  logout: vi.fn(),
}))

function Consumer() {
  const { completeW3OAuth2Login: complete, user } = useRole()
  return (
    <>
      <button type="button" onClick={() => complete()}>
        完成 W3 登录
      </button>
      <span>{user?.username || '未登录'}</span>
    </>
  )
}

describe('RoleProvider W3 OAuth2', () => {
  beforeEach(() => {
    completeW3OAuth2Login.mockReset()
    fetchMe.mockReset()
  })

  it('stores the one-time project token and reuses the normal user context', async () => {
    const user = { username: 'E10001', permissions: ['resume.view'] }
    completeW3OAuth2Login.mockResolvedValue({
      data: { token: 'project-token', user },
    })
    fetchMe.mockResolvedValue({ data: user })
    render(
      <RoleProvider>
        <Consumer />
      </RoleProvider>,
    )

    await userEvent.click(screen.getByRole('button', { name: '完成 W3 登录' }))

    expect(await screen.findByText('E10001')).toBeTruthy()
    expect(localStorage.getItem('srf_token')).toBe('project-token')
    await waitFor(() => expect(fetchMe).toHaveBeenCalledTimes(1))
  })
})
