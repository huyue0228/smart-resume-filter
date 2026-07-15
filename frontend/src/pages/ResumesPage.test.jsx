import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import ResumesPage from './ResumesPage'

const candidate = vi.hoisted(() => ({
  id: 1,
  name: '张三',
  phone: '13800000000',
  highest_major: '计算机',
  first_degree_school: '南京大学',
  first_degree_platform: '平台A',
  highest_degree_school: '浙江大学',
  highest_degree_platform: '平台B',
  current_rank: 1,
  current_apply_id: 'A001',
  workflow_status: 'in_progress',
  system_status_label: '待处理',
  reason_type: 'none',
  reason_text: '',
  workflow_id: 9,
  current_attempt: null,
  current_resume: {
    id: 11,
    apply_id: 'A001',
    volunteer_rank: 1,
    entity: '主体A',
    position_name: '后端工程师',
    job_category: '技术类',
    status: '待处理',
    resume_file: 'A001.pdf',
  },
  preview_resume: {
    id: 11,
    apply_id: 'A001',
    volunteer_rank: 1,
    entity: '主体A',
    position_name: '后端工程师',
    job_category: '技术类',
    status: '待处理',
    resume_file: 'A001.pdf',
  },
  resumes: [
    {
      id: 11,
      apply_id: 'A001',
      volunteer_rank: 1,
      entity: '主体A',
      position_name: '后端工程师',
      job_category: '技术类',
      status: '待处理',
      resume_file: 'A001.pdf',
    },
    {
      id: 12,
      apply_id: 'A002',
      volunteer_rank: 2,
      entity: '主体B',
      position_name: '产品经理',
      job_category: '产品类',
      status: '待处理',
      resume_file: '',
    },
  ],
  attempts: [],
}))

const roleState = vi.hoisted(() => ({
  permissions: new Set(['attempt.view_all']),
  contact: null,
  isContact: false,
  isSecondaryContact: false,
}))

vi.mock('@ant-design/pro-components', () => ({
  PageContainer: ({ children }) => <div>{children}</div>,
}))

vi.mock('../contexts/RoleContext', () => ({
  useRole: () => ({
    hasPermission: (code) => roleState.permissions.has(code),
    contact: roleState.contact,
    isContact: roleState.isContact,
    isSecondaryContact: roleState.isSecondaryContact,
  }),
}))

vi.mock('../components/useProcessRunner', () => ({
  useProcessRunner: () => ({ run: vi.fn() }),
}))

vi.mock('../components/ImportButton', () => ({ default: () => null }))

vi.mock('../components/ResumePreview', () => ({
  default: ({ resume }) => (
    <div data-testid="resume-preview">
      {resume?.resume_file ? `preview:${resume.apply_id}` : `missing:${resume?.apply_id || 'none'}`}
    </div>
  ),
}))

vi.mock('../components/SmartDataTable', () => ({
  default: ({ tableId, columns = [], dataSource = [], onRowClick }) => (
    <section
      data-testid={`table-${tableId}`}
      data-filter-count={columns.filter((column) => column.filter).length}
      data-columns={columns.map((column) => column.title).join(',')}
    >
      {tableId === 'candidates' && (
        <button type="button" onClick={() => onRowClick?.(candidate)}>
          打开候选人
        </button>
      )}
      {dataSource.map((record) => (
        <div key={record.id}>
          <button type="button" onClick={() => onRowClick?.(record)}>
            {record.apply_id || record.id}
          </button>
          {tableId === 'candidate-resumes' && (
            <span data-testid={`entity-${record.id}`}>
              {columns.find((column) => column.dataIndex === 'entity')?.render?.(record.entity, record)}
            </span>
          )}
        </div>
      ))}
    </section>
  ),
}))

vi.mock('../api/services', () => ({
  deleteCandidate: vi.fn(),
  exportCandidates: vi.fn(),
  fetchCandidates: vi.fn(),
  fetchCandidateFilterOptions: vi.fn(),
  fetchUndoStatus: vi.fn(),
  undoLastImport: vi.fn(),
  fetchContacts: vi.fn(),
  manualAssignResume: vi.fn(),
  fetchAgentDecisions: vi.fn().mockResolvedValue({ data: { results: [] } }),
  retryAgentDecision: vi.fn(),
  fetchAllocationMode: vi.fn(),
  dispatchAllocation: vi.fn(),
  confirmReviewAllocation: vi.fn(),
  cancelAllocation: vi.fn(),
  cancelReviewAllocation: vi.fn(),
  transferAllocationToManual: vi.fn(),
  bulkDispatchCandidates: vi.fn(),
  assignSubContact: vi.fn(),
  fetchEligibleSubContacts: vi.fn(),
  submitAllocationFeedback: vi.fn(),
  exportAllocations: vi.fn(),
  exportResumeResultReport: vi.fn(),
}))

describe('ResumesPage detail', () => {
  beforeEach(() => {
    candidate.current_attempt = null
    candidate.attempts = []
    roleState.permissions = new Set(['attempt.view_all'])
    roleState.contact = null
    roleState.isContact = false
    roleState.isSecondaryContact = false
  })

  it('removes detail filters and switches preview by volunteer row', async () => {
    render(<MemoryRouter><ResumesPage /></MemoryRouter>)
    await userEvent.click(screen.getByRole('button', { name: '打开候选人' }))

    await waitFor(() => expect(screen.getByTestId('resume-preview').textContent).toBe('preview:A001'))

    for (const tableId of ['candidate-resumes', 'candidate-attempts', 'candidate-ai-decisions']) {
      expect(screen.getByTestId(`table-${tableId}`).dataset.filterCount).toBe('0')
    }
    expect(screen.getByTestId('table-candidate-resumes').dataset.columns).not.toContain('预览')
    expect(screen.queryByText('第一学历标签')).toBeNull()
    expect(screen.queryByText('最高学历标签')).toBeNull()
    expect(screen.getByText('平台A').classList.contains('ant-tag')).toBe(true)
    expect(screen.getByText('平台B').classList.contains('ant-tag')).toBe(true)
    const entityATag = screen.getByTestId('entity-11').querySelector('.ant-tag')
    const entityBTag = screen.getByTestId('entity-12').querySelector('.ant-tag')
    expect(entityATag.textContent).toBe('主体A')
    expect(entityBTag.textContent).toBe('主体B')
    expect(entityATag.className).not.toBe(entityBTag.className)

    await userEvent.click(screen.getByRole('button', { name: 'A002' }))
    expect(screen.getByTestId('resume-preview').textContent).toBe('missing:A002')
  })

  it('shows feedback to the bound secondary contact before transfer', async () => {
    candidate.current_attempt = {
      id: 21,
      status: 'dispatched_l2',
      contact: 10,
      sub_contact: null,
      feedback_at: null,
    }
    candidate.attempts = [candidate.current_attempt]
    roleState.permissions = new Set(['attempt.feedback', 'attempt.view_received'])
    roleState.contact = { id: 10 }
    roleState.isContact = true
    roleState.isSecondaryContact = true

    render(<MemoryRouter><ResumesPage /></MemoryRouter>)
    await userEvent.click(screen.getByRole('button', { name: '打开候选人' }))

    expect(screen.getByRole('button', { name: '提交反馈' })).not.toBeNull()
  })

  it('hides feedback from the secondary contact after transfer', async () => {
    candidate.current_attempt = {
      id: 22,
      status: 'assigned_l3',
      contact: 10,
      sub_contact: 11,
      feedback_at: null,
    }
    candidate.attempts = [candidate.current_attempt]
    roleState.permissions = new Set(['attempt.feedback', 'attempt.view_received'])
    roleState.contact = { id: 10 }
    roleState.isContact = true
    roleState.isSecondaryContact = true

    render(<MemoryRouter><ResumesPage /></MemoryRouter>)
    await userEvent.click(screen.getByRole('button', { name: '打开候选人' }))

    expect(screen.queryByRole('button', { name: '提交反馈' })).toBeNull()
  })
})
