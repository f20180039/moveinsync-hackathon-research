import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { DispatchResponse } from '../api/types.ts'
import { BriefPage } from './BriefPage.tsx'

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

function jsonResponse(body: unknown) {
  return Promise.resolve({ ok: true, json: async () => body } as Response)
}

function notFound() {
  return Promise.resolve({ ok: false, status: 404, statusText: 'Not Found', text: async () => '' } as Response)
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('BriefPage', () => {
  // The page's own <h1> moved to the shell's top bar (nav.ts titles every
  // route), so a page rendered in isolation has no heading of its own --
  // asserting one here would pin a duplicate back into place.
  it('renders without a heading of its own, since the shell titles the page', () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => notFound()),
    )

    render(<BriefPage runId="run-1" />)

    expect(screen.queryByRole('heading', { level: 1 })).not.toBeInTheDocument()
  })

  it('renders per-channel dispatch results after Dispatch is pressed, with human-readable labels', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/api/dispatch/log')) return notFound()
      return jsonResponse(dispatchResponse)
    })
    vi.stubGlobal('fetch', fetchMock)

    const user = userEvent.setup()
    render(<BriefPage runId="run-1" />)

    await user.click(screen.getByRole('button', { name: /dispatch/i }))

    // "TRANSPORT_MANAGER" never renders raw -- humanised via labels.ts.
    // Scoped to the results list: the audience select also renders
    // "Transport manager" as an <option>.
    const resultsList = await screen
      .findByText(/Slack · delivered/)
      .then((el) => el.closest('.brief-preview__dispatch-results') as HTMLElement)
    expect(within(resultsList).getByText('Transport manager')).toBeInTheDocument()
    expect(within(resultsList).getByText(/Slack · delivered/)).toBeInTheDocument()
    expect(within(resultsList).getByText(/Email · not configured/)).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/dispatch/run-1'),
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('shows the full brief text and a human-readable source after Preview brief', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/api/dispatch/log')) return notFound()
      if (url.includes('/brief')) {
        return jsonResponse({ runId: 'run-1', audience: 'TRANSPORT_MANAGER', brief: 'Full brief text.', source: 'template' })
      }
      return notFound()
    })
    vi.stubGlobal('fetch', fetchMock)

    const user = userEvent.setup()
    render(<BriefPage runId="run-1" />)

    await user.click(screen.getByRole('button', { name: /preview brief/i }))

    expect(await screen.findByText('Full brief text.')).toBeInTheDocument()
    expect(screen.getByText('Source: Template')).toBeInTheDocument()
  })

  it('does not show a dispatch log section when the optional endpoint is absent', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => notFound()),
    )

    render(<BriefPage runId="run-1" />)

    // Give the (rejected) dispatch-log fetch a tick to settle.
    await new Promise((resolve) => setTimeout(resolve, 10))

    expect(screen.queryByText('Dispatch log')).not.toBeInTheDocument()
  })
})
