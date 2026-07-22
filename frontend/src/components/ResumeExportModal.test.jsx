import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ResumeExportModal from './ResumeExportModal'
import { fetchCandidateExportFields } from '../api/services'

vi.mock('../api/services', () => ({
  fetchCandidateExportFields: vi.fn(),
}))

const catalog = {
  version: 2,
  groups: [
    {
      key: 'candidate',
      label: '候选人',
      fields: [
        { key: 'candidate_name', label: '姓名', default_selected: true },
        { key: 'candidate_phone', label: '手机号', default_selected: true },
      ],
    },
    {
      key: 'application',
      label: '当前投递',
      fields: [
        { key: 'current_apply_id', label: '应聘ID', default_selected: true },
        { key: 'entity', label: '主体', default_selected: false },
      ],
    },
  ],
}

describe('ResumeExportModal', () => {
  beforeEach(() => {
    localStorage.clear()
    fetchCandidateExportFields.mockReset()
    fetchCandidateExportFields.mockResolvedValue({ data: catalog })
  })

  it('selects server defaults and supports clear, restore defaults and select all', async () => {
    const user = userEvent.setup()
    render(
      <ResumeExportModal
        open
        userKey="7"
        onCancel={vi.fn()}
        onExport={vi.fn()}
      />,
    )

    expect((await screen.findByRole('checkbox', { name: '姓名' })).checked).toBe(true)
    expect(screen.getByRole('checkbox', { name: '手机号' }).checked).toBe(true)
    expect(screen.getByRole('checkbox', { name: '应聘ID' }).checked).toBe(true)
    expect(screen.getByRole('checkbox', { name: '主体' }).checked).toBe(false)

    await user.click(screen.getByRole('button', { name: /清\s*空/ }))
    expect(screen.getByRole('button', { name: '导出 ZIP' }).disabled).toBe(true)

    await user.click(screen.getByRole('button', { name: '恢复默认' }))
    expect(screen.getByRole('checkbox', { name: '姓名' }).checked).toBe(true)
    expect(screen.getByRole('checkbox', { name: '主体' }).checked).toBe(false)

    await user.click(screen.getByRole('button', { name: /全\s*选/ }))
    expect(screen.getByRole('checkbox', { name: '主体' }).checked).toBe(true)
  })

  it('keeps valid remembered fields per user and drops removed catalog keys', async () => {
    localStorage.setItem('srf.resume-export-fields:alice', JSON.stringify({
      version: 1,
      fields: ['removed_field', 'entity'],
    }))
    render(
      <ResumeExportModal
        open
        userKey="alice"
        onCancel={vi.fn()}
        onExport={vi.fn()}
      />,
    )

    expect((await screen.findByRole('checkbox', { name: '主体' })).checked).toBe(true)
    expect(screen.getByRole('checkbox', { name: '姓名' }).checked).toBe(false)
  })

  it('falls back to defaults when remembered fields are all invalid', async () => {
    localStorage.setItem('srf.resume-export-fields:alice', JSON.stringify({
      version: 1,
      fields: ['removed_field'],
    }))
    render(
      <ResumeExportModal
        open
        userKey="alice"
        onCancel={vi.fn()}
        onExport={vi.fn()}
      />,
    )

    expect((await screen.findByRole('checkbox', { name: '姓名' })).checked).toBe(true)
    expect(screen.getByRole('checkbox', { name: '应聘ID' }).checked).toBe(true)
  })

  it('submits and remembers fields in stable catalog order', async () => {
    const user = userEvent.setup()
    const onExport = vi.fn()
    render(
      <ResumeExportModal
        open
        userKey="bob"
        onCancel={vi.fn()}
        onExport={onExport}
      />,
    )
    await screen.findByRole('checkbox', { name: '姓名' })

    await user.click(screen.getByRole('button', { name: /清\s*空/ }))
    await user.click(screen.getByRole('checkbox', { name: '主体' }))
    await user.click(screen.getByRole('checkbox', { name: '姓名' }))
    await user.click(screen.getByRole('button', { name: '导出 ZIP' }))

    expect(onExport).toHaveBeenCalledWith(['candidate_name', 'entity'])
    await waitFor(() => expect(JSON.parse(
      localStorage.getItem('srf.resume-export-fields:bob'),
    )).toEqual({ version: 2, fields: ['candidate_name', 'entity'] }))
  })
})
