import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import DepartmentsPage from './DepartmentsPage'

const mocks = vi.hoisted(() => ({
  deleteContact: vi.fn(),
  fetchConfig: vi.fn(),
  updateConfig: vi.fn(),
  hasPermission: vi.fn(),
  reload: vi.fn(),
  reloadOptions: vi.fn(),
  success: vi.fn(),
}))

vi.mock('@ant-design/pro-components', () => ({
  PageContainer: ({ children }) => <div>{children}</div>,
}))

vi.mock('antd', () => ({
  message: { success: mocks.success, error: vi.fn() },
  Popconfirm: ({ children, onConfirm }) => (
    <div>
      {children}
      <button type="button" onClick={onConfirm}>确认删除</button>
    </div>
  ),
  Space: ({ children }) => <div>{children}</div>,
  Switch: ({ checked, loading, onChange, ...props }) => (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={loading}
      onClick={() => onChange(!checked)}
      {...props}
    >
      {checked ? '开启' : '关闭'}
    </button>
  ),
  Tag: ({ children }) => <span>{children}</span>,
}))

vi.mock('../contexts/roleState', () => ({
  useRole: () => ({ hasPermission: mocks.hasPermission }),
}))

vi.mock('../api/services', () => ({
  deleteContact: mocks.deleteContact,
  fetchConfig: mocks.fetchConfig,
  fetchContactFilterOptions: vi.fn(),
  fetchContacts: vi.fn(),
  updateConfig: mocks.updateConfig,
}))

vi.mock('../components/ImportButton', () => ({ default: () => null }))

vi.mock('../components/SmartDataTable', () => ({
  default: ({ actionRef, columns }) => {
    actionRef.current = {
      reload: mocks.reload,
      reloadOptions: mocks.reloadOptions,
    }
    const actionColumn = columns.find((column) => column.valueType === 'option')
    return <div>{actionColumn.render(null, { id: 7 })}</div>
  },
}))

describe('DepartmentsPage', () => {
  beforeEach(() => {
    mocks.deleteContact.mockReset()
    mocks.deleteContact.mockResolvedValue({})
    mocks.fetchConfig.mockReset()
    mocks.fetchConfig.mockResolvedValue({ data: { key: 'welink_enabled', value: false } })
    mocks.updateConfig.mockReset()
    mocks.updateConfig.mockResolvedValue({ data: { key: 'welink_enabled', value: true } })
    mocks.hasPermission.mockReset()
    mocks.hasPermission.mockImplementation((code) => code === 'department.manage')
    mocks.reload.mockReset()
    mocks.reloadOptions.mockReset()
    mocks.success.mockReset()
  })

  it('refreshes table data and filter options after deleting a contact', async () => {
    render(<DepartmentsPage />)

    await userEvent.click(screen.getByRole('button', { name: '确认删除' }))

    await waitFor(() => expect(mocks.deleteContact).toHaveBeenCalledWith(7))
    expect(mocks.reload).toHaveBeenCalledOnce()
    expect(mocks.reloadOptions).toHaveBeenCalledOnce()
    expect(mocks.success).toHaveBeenCalledWith('已删除')
  })

  it('manages the WeLink notification switch on the contacts page', async () => {
    render(<DepartmentsPage />)

    await waitFor(() => expect(mocks.fetchConfig).toHaveBeenCalledWith('welink_enabled'))
    await userEvent.click(screen.getByRole('switch', { name: 'WeLink 通知' }))

    await waitFor(() => expect(mocks.updateConfig).toHaveBeenCalledWith('welink_enabled', true))
    expect(mocks.success).toHaveBeenCalledWith('已开启 WeLink 通知')
  })

  it('hides the WeLink switch without contact management permission', () => {
    mocks.hasPermission.mockReturnValue(false)

    render(<DepartmentsPage />)

    expect(screen.queryByRole('switch', { name: 'WeLink 通知' })).toBeNull()
    expect(mocks.fetchConfig).not.toHaveBeenCalled()
  })
})
