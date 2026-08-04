import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import PromptManagementPage from './PromptManagementPage'
import {
  fetchAIPrompts,
  fetchAIPromptVersion,
  fetchAIPromptVersions,
  publishAIPromptDraft,
  resetAIPromptDraft,
  restoreAIPromptVersion,
  saveAIPromptDraft,
  testAIPromptDraft,
} from '../api/services'

vi.mock('../api/services', () => ({
  fetchAIPrompts: vi.fn(),
  fetchAIPromptVersion: vi.fn(),
  fetchAIPromptVersions: vi.fn(),
  publishAIPromptDraft: vi.fn(),
  resetAIPromptDraft: vi.fn(),
  restoreAIPromptVersion: vi.fn(),
  saveAIPromptDraft: vi.fn(),
  testAIPromptDraft: vi.fn(),
}))

vi.mock('antd', async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    Popconfirm: ({ children, onConfirm, title }) => (
      <span>
        {children}
        <button type="button" aria-label={`确认-${title}`} onClick={onConfirm}>
          确认
        </button>
      </span>
    ),
  }
})

const moduleDefinitions = [
  ['screening_role_goal', '筛选角色与任务目标'],
  ['screening_rule_guardrails', '筛选业务边界'],
  ['screening_job_evaluation', '岗位适配评价口径'],
  ['screening_ai_specialist', 'AI 专项人才识别'],
  ['school_province_inference', '院校省份判断'],
].map(([key, label], index) => ({
  key,
  label,
  description: `${label}说明`,
  order: index + 1,
  max_chars: 8000,
}))

const baseModules = Object.fromEntries(
  moduleDefinitions.map(({ key, label }) => [key, `${label}默认内容`]),
)

function promptRecord(overrides = {}) {
  return {
    version: 'draft-resume-screening-v2',
    status: 'draft',
    lock_version: 1,
    modules: baseModules,
    content_hash: 'hash',
    test_valid: false,
    test_model_name: '',
    tested_at: null,
    updated_by_username: 'admin',
    published_by_username: '',
    published_at: null,
    ...overrides,
  }
}

function managementPayload(overrides = {}) {
  return {
    module_definitions: moduleDefinitions,
    limits: { module_max_chars: 8000, total_max_chars: 24000 },
    default_modules: baseModules,
    assembly_preview: {
      resume_screening: {
        editable_module_order: moduleDefinitions.slice(0, 4).map(({ key }) => key),
        fixed_sections: ['最小安全底座', '后端动态 JSON 数据载荷'],
      },
      school_province: {
        editable_module_order: ['school_province_inference'],
        fixed_sections: ['最小安全底座', '省份白名单'],
      },
    },
    active: promptRecord({
      version: 'resume-screening-v2',
      status: 'active',
      lock_version: 0,
      published_at: '2026-07-30T08:00:00Z',
    }),
    draft: promptRecord(),
    ...overrides,
  }
}

describe('PromptManagementPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    fetchAIPrompts.mockResolvedValue({ data: managementPayload() })
    fetchAIPromptVersions.mockResolvedValue({
      data: {
        count: 1,
        results: [
          promptRecord({
            version: 'resume-screening-v2',
            status: 'active',
            release_sequence: 0,
            published_at: '2026-07-30T08:00:00Z',
          }),
        ],
      },
    })
    fetchAIPromptVersion.mockResolvedValue({
      data: promptRecord({
        version: 'resume-screening-v2',
        status: 'active',
      }),
    })
    saveAIPromptDraft.mockImplementation(async (modules) => ({
      data: promptRecord({ lock_version: 2, modules }),
    }))
    testAIPromptDraft.mockResolvedValue({
      data: {
        ok: true,
        detail: 'Prompt 草稿真实模型测试通过',
        draft: promptRecord({
          lock_version: 2,
          test_valid: true,
          test_model_name: 'model-a',
          tested_at: '2026-07-30T09:00:00Z',
        }),
      },
    })
    publishAIPromptDraft.mockResolvedValue({
      data: {
        detail: 'Prompt 已发布，只影响新提交的 AI 任务',
        active: promptRecord({
          version: 'prompt-v000001-12345678',
          status: 'active',
          lock_version: 3,
          test_valid: true,
        }),
        draft: promptRecord({
          version: 'draft-prompt-v000001-12345678',
          lock_version: 0,
        }),
      },
    })
    resetAIPromptDraft.mockResolvedValue({ data: promptRecord({ lock_version: 2 }) })
    restoreAIPromptVersion.mockResolvedValue({
      data: promptRecord({
        lock_version: 2,
        restored_from_version: 'resume-screening-v2',
      }),
    })
  })

  it('edits five modules and enforces save, test and publish order', async () => {
    const user = userEvent.setup()
    render(<PromptManagementPage />)

    expect((await screen.findAllByText('resume-screening-v2')).length).toBeGreaterThan(0)
    expect(screen.getAllByRole('textbox')).toHaveLength(5)
    const testButton = screen.getByRole('button', { name: '真实模型测试' })
    const publishButton = screen.getByRole('button', { name: '发 布' })
    expect(publishButton.disabled).toBe(true)

    const roleEditor = screen.getByRole('textbox', { name: '筛选角色与任务目标' })
    await user.clear(roleEditor)
    await user.type(roleEditor, '新的角色目标')
    expect(testButton.disabled).toBe(true)

    await user.click(screen.getByRole('button', { name: '保存共享草稿' }))
    await waitFor(() => expect(saveAIPromptDraft).toHaveBeenCalledWith(
      expect.objectContaining({ screening_role_goal: '新的角色目标' }),
      1,
    ))
    expect(testButton.disabled).toBe(false)

    await user.click(testButton)
    await waitFor(() => expect(testAIPromptDraft).toHaveBeenCalledTimes(1))
    expect(publishButton.disabled).toBe(false)

    await user.click(screen.getByRole('button', {
      name: '确认-发布当前草稿？',
    }))
    await waitFor(() => expect(publishAIPromptDraft).toHaveBeenCalledWith(2))
    expect(await screen.findByText('prompt-v000001-12345678')).toBeTruthy()
  })

  it('reloads the shared draft after an optimistic lock conflict', async () => {
    const user = userEvent.setup()
    saveAIPromptDraft.mockRejectedValueOnce({
      response: { status: 409, data: { detail: '共享草稿已被其他管理员更新' } },
    })
    render(<PromptManagementPage />)
    const editor = await screen.findByRole('textbox', { name: '筛选角色与任务目标' })

    await user.type(editor, '更新')
    await user.click(screen.getByRole('button', { name: '保存共享草稿' }))

    await waitFor(() => expect(fetchAIPrompts).toHaveBeenCalledTimes(2))
  })

  it('shows module-level history differences and restores history to draft', async () => {
    const user = userEvent.setup()
    fetchAIPromptVersion.mockResolvedValueOnce({
      data: promptRecord({
        version: 'resume-screening-v2',
        status: 'archived',
        modules: {
          ...baseModules,
          screening_role_goal: '历史角色目标',
        },
      }),
    })
    render(<PromptManagementPage />)

    await user.click(await screen.findByRole('button', { name: '查看模块差异' }))
    expect(await screen.findByText('历史角色目标')).toBeTruthy()
    expect(screen.getByText('与当前激活版本不同')).toBeTruthy()

    await user.click(screen.getByRole('button', {
      name: '确认-复制该历史版本到共享草稿？',
    }))
    await waitFor(() => expect(restoreAIPromptVersion).toHaveBeenCalledWith(
      'resume-screening-v2',
      1,
    ))
  })
})
