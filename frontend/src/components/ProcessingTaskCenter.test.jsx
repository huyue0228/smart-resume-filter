import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import ProcessingTaskCenter from './ProcessingTaskCenter'

const fetchPipelineRuns = vi.hoisted(() => vi.fn())

vi.mock('../api/services', () => ({
  fetchPipelineRuns,
  cancelPipelineRun: vi.fn(),
}))

function CurrentLocation() {
  const location = useLocation()
  return <output data-testid="location">{`${location.pathname}${location.search}`}</output>
}

describe('ProcessingTaskCenter', () => {
  it('opens the corresponding AI result in the candidate list', async () => {
    fetchPipelineRuns.mockResolvedValue({
      data: {
        results: [{
          id: 18,
          step: 'step2',
          mode: 'ai',
          status: 'success',
          created_at: '2026-07-14T10:00:00Z',
          elapsed_seconds: 12,
          total_count: 2,
          processed_count: 2,
          success_count: 2,
          review_count: 1,
          dispatch_count: 1,
        }],
      },
    })

    render(
      <MemoryRouter>
        <ProcessingTaskCenter />
        <CurrentLocation />
      </MemoryRouter>,
    )

    await userEvent.click(screen.getByRole('button', { name: /处理任务/ }))
    const reviewButton = await screen.findByRole('button', {
      name: '筛选本任务待复核简历 1 名',
    })
    await userEvent.click(reviewButton)

    await waitFor(() => expect(screen.getByTestId('location').textContent).toBe(
      '/resumes?processing_run_id=18&processing_result=review',
    ))
  })
})
