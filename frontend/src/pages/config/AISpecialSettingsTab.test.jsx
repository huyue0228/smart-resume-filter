import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import AISpecialSettingsTab from './AISpecialSettingsTab'
import { saveAISpecialSettings } from './aiSpecialSettings'
import {
  fetchAIConnectionSettings,
  updateAIConnectionSetting,
} from '../../api/services'

vi.mock('../../api/services', () => ({
  fetchAIConnectionSettings: vi.fn(),
  updateAIConnectionSetting: vi.fn(),
}))

const settingsResponse = {
  settings: [
    { key: 'ai_special_route_enabled', section: 'special_route', value: false },
    { key: 'ai_special_route_threshold', section: 'special_route', value: 0.9 },
    { key: 'ai_special_route_secondary_contact_id', section: 'special_route', value: 11 },
    { key: 'ai_special_route_tertiary_contact_id', section: 'special_route', value: 21 },
  ],
  contacts: [
    {
      id: 11,
      name: '研发二级接口人',
      employee_no: 'S11',
      contact_level: 'secondary',
      department: 101,
      department_name: '研发部',
      parent_department: null,
    },
    {
      id: 21,
      name: '算法三级接口人',
      employee_no: 'T21',
      contact_level: 'tertiary',
      department: 201,
      department_name: '算法组',
      parent_department: 101,
    },
    {
      id: 22,
      name: '产品三级接口人',
      employee_no: 'T22',
      contact_level: 'tertiary',
      department: 202,
      department_name: '产品组',
      parent_department: 102,
    },
  ],
}

describe('AISpecialSettingsTab', () => {
  beforeEach(() => {
    fetchAIConnectionSettings.mockReset()
    updateAIConnectionSetting.mockReset()
    fetchAIConnectionSettings.mockResolvedValue({ data: settingsResponse })
    updateAIConnectionSetting.mockResolvedValue({ data: {} })
  })

  it('loads the special settings and saves the enable switch', async () => {
    const user = userEvent.setup()
    render(<AISpecialSettingsTab />)

    const enabled = await screen.findByRole('switch', { name: '启用 AI 专项' })
    expect(enabled.getAttribute('aria-checked')).toBe('false')
    expect(screen.getByRole('spinbutton', { name: 'AI 专项触发阈值' }).value).toBe('0.90')

    await user.click(enabled)
    await user.click(screen.getByRole('button', { name: '保存 AI 专项配置' }))

    await waitFor(() => expect(updateAIConnectionSetting).toHaveBeenCalledWith(
      'ai_special_route_enabled',
      true,
    ))
  })

  it('safely disables an enabled route before changing its targets', async () => {
    const update = vi.fn().mockResolvedValue({ data: {} })
    const persisted = {
      ai_special_route_enabled: true,
      ai_special_route_threshold: 0.9,
      ai_special_route_secondary_contact_id: 11,
      ai_special_route_tertiary_contact_id: 21,
    }
    const drafts = {
      ...persisted,
      ai_special_route_secondary_contact_id: 12,
      ai_special_route_tertiary_contact_id: 22,
    }

    await saveAISpecialSettings({ persisted, drafts, update })

    expect(update.mock.calls).toEqual([
      ['ai_special_route_enabled', false],
      ['ai_special_route_secondary_contact_id', 12],
      ['ai_special_route_tertiary_contact_id', 22],
      ['ai_special_route_enabled', true],
    ])
  })
})
