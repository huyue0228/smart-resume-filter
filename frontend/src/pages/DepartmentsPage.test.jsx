import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import DepartmentsPage from './DepartmentsPage'

const mocks = vi.hoisted(() => ({
  deleteContact: vi.fn(),
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
  Tag: ({ children }) => <span>{children}</span>,
}))

vi.mock('../api/services', () => ({
  deleteContact: mocks.deleteContact,
  fetchContactFilterOptions: vi.fn(),
  fetchContacts: vi.fn(),
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
})
