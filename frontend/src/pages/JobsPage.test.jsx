import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import JobsPage from './JobsPage'

const mocks = vi.hoisted(() => ({
  columns: [],
  fetchDepartments: vi.fn(),
}))

vi.mock('@ant-design/pro-components', () => ({
  PageContainer: ({ children }) => <div>{children}</div>,
  ModalForm: ({ children }) => <form>{children}</form>,
  ProFormDigit: () => null,
  ProFormSelect: () => null,
  ProFormSwitch: () => null,
  ProFormText: () => null,
  ProFormTextArea: ({ label, rules }) => (
    <textarea
      aria-label={label}
      data-required={rules?.some((rule) => rule.required) ? 'true' : 'false'}
    />
  ),
}))

vi.mock('antd', () => ({
  Button: ({ children }) => <button type="button">{children}</button>,
  Popconfirm: ({ children }) => <>{children}</>,
  Space: ({ children }) => <div>{children}</div>,
  Tag: ({ children }) => <span>{children}</span>,
  message: { success: vi.fn() },
}))

vi.mock('../contexts/roleState', () => ({
  useRole: () => ({ hasPermission: () => false }),
}))

vi.mock('../api/services', () => ({
  createJob: vi.fn(),
  deleteJob: vi.fn(),
  fetchDepartments: mocks.fetchDepartments,
  fetchJobFilterOptions: vi.fn(),
  fetchJobs: vi.fn(),
  updateJob: vi.fn(),
}))

vi.mock('../components/ImportButton', () => ({ default: () => null }))

vi.mock('../components/SmartDataTable', () => ({
  default: ({ columns }) => {
    mocks.columns = columns
    return <div>{columns.map((column) => column.title).join('、')}</div>
  },
}))

describe('JobsPage', () => {
  beforeEach(() => {
    mocks.columns = []
    mocks.fetchDepartments.mockReset()
    mocks.fetchDepartments.mockResolvedValue({ data: { results: [] } })
  })

  it('shows, filters and requires job responsibilities', () => {
    render(<JobsPage />)

    const responsibilitiesColumn = mocks.columns.find(
      (column) => column.dataIndex === 'responsibilities',
    )
    expect(responsibilitiesColumn?.title).toBe('工作职责')
    expect(responsibilitiesColumn?.filter).toMatchObject({
      type: 'text',
      param: 'responsibilities',
    })
    expect(
      screen.getByRole('textbox', { name: '工作职责' }).getAttribute('data-required'),
    ).toBe('true')
  })
})
