import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ImportButton from './ImportButton'

const importData = vi.hoisted(() => vi.fn())

vi.mock('../api/services', () => ({ importData }))

describe('ImportButton processing mode', () => {
  beforeEach(() => {
    importData.mockReset()
    importData.mockResolvedValue({ data: { detail: '导入完成' } })
  })

  it('submits the selected AI mode for resume uploads when AI is ready', async () => {
    const user = userEvent.setup()
    render(
      <ImportButton
        buttonText="上传简历"
        fields={[{ key: 'resume_package', label: '简历包', accept: '.zip' }]}
        selectProcessingMode
        aiReady
      />,
    )

    await user.click(screen.getByRole('button', { name: /上传简历/ }))
    const input = document.querySelector('input[type="file"]')
    await user.upload(input, new File(['resume'], '简历包.zip', { type: 'application/zip' }))
    await user.click(screen.getByText('AI'))
    await user.click(screen.getByRole('button', { name: '开始导入' }))

    await waitFor(() => expect(importData).toHaveBeenCalledTimes(1))
    const formData = importData.mock.calls[0][0]
    expect(formData.get('mode')).toBe('incremental')
    expect(formData.get('processing_mode')).toBe('ai')
    expect(formData.get('resume_package').name).toBe('简历包.zip')
  })
})
