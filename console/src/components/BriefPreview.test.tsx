import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { DispatchResponse } from '../api/types.ts'
import { BriefPreview } from './BriefPreview.tsx'

const dispatchResponse: DispatchResponse = {
  runId: 'run-1',
  dispatched: [
    {
      audience: 'TRANSPORT_MANAGER',
      tier: 'BREACH',
      findingIds: ['563931f15cdd'],
      channels: [
        { channel: 'slack', delivered: true, detail: 'ok' },
        { channel: 'email', delivered: false, detail: 'not configured' },
      ],
    },
  ],
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('BriefPreview', () => {
  it('renders per-channel dispatch results after Dispatch is pressed', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => dispatchResponse,
    })
    vi.stubGlobal('fetch', fetchMock)

    const user = userEvent.setup()
    render(<BriefPreview runId="run-1" />)

    await user.click(screen.getByRole('button', { name: /dispatch/i }))

    expect(await screen.findByText(/slack · delivered/)).toBeInTheDocument()
    expect(await screen.findByText(/email · not configured/)).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/dispatch/run-1'),
      expect.objectContaining({ method: 'POST' }),
    )
  })
})
