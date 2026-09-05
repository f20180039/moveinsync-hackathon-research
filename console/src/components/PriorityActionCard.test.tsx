import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { DispatchResponse, Finding } from '../api/types.ts'
import { PriorityActionCard } from './PriorityActionCard.tsx'

function makeFinding(overrides: Partial<Finding> = {}): Finding {
  return {
    id: '1f4f6f672a4f',
    metricId: 'vendor_ota',
    metricLabel: 'Vendor on-time share',
    unit: '%',
    sliceLabel: 'vendor Vikram Mikhailov Travel',
    tier: 'BREACH',
    cause: 'PEER_LAGGARD',
    observed: 32.31,
    gap: 26.79,
    confidence: 0.94,
    audiences: ['FACILITIES_HEAD', 'TRANSPORT_MANAGER'],
    references: [
      { kind: 'PEER', value: 59.1, label: 'peer median' },
      { kind: 'TREND', value: 41.8, label: '4-week average' },
    ],
    evidenceSql: "SELECT 1 WHERE vendor_id = 'Vikram Mikhailov Travel'",
    ...overrides,
  }
}

function notFound() {
  return Promise.resolve({ ok: false, status: 404, statusText: 'Not Found', text: async () => '' } as Response)
}

function jsonResponse(body: unknown) {
  return Promise.resolve({ ok: true, json: async () => body } as Response)
}

afterEach(() => {
  vi.unstubAllGlobals()
  window.localStorage.clear()
})

describe('PriorityActionCard', () => {
  it('renders Why, Impact and Compared against, plus all three buttons', async () => {
    vi.stubGlobal('fetch', vi.fn(() => notFound()))
    const finding = makeFinding()

    render(<PriorityActionCard finding={finding} runId="run-1" onDismiss={() => {}} />)

    expect(screen.getByText('behind comparable peers')).toBeInTheDocument() // Why (cause phrase fallback)
    expect(screen.getByText(/26\.79%/)).toBeInTheDocument() // Impact (gap, in the metric's unit)
    expect(screen.getByText(/peer median 59\.1%/)).toBeInTheDocument() // Compared against
    expect(screen.getByText(/4-week average 41\.8%/)).toBeInTheDocument()

    expect(screen.getByRole('button', { name: /investigate/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /escalate/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /dismiss/i })).toBeInTheDocument()
  })

  it('shows the top-2 contributors in Why from finding.owns, with zero /decompose requests', async () => {
    const fetchMock = vi.fn(() => notFound())
    vi.stubGlobal('fetch', fetchMock)
    const finding = makeFinding({
      owns: [
        { value: 'POOJA SOKOLOV TRAVEL', pointsOfGap: 4.1, n: 50 },
        { value: 'Vikram Mikhailov Travel', pointsOfGap: 1.3, n: 120 },
      ],
    })

    render(<PriorityActionCard finding={finding} runId="run-1" onDismiss={() => {}} />)

    // owns[].value is humanised only when it looks like an enum code (all
    // uppercase); a real name with mixed case renders verbatim.
    expect(
      screen.getByText('Pooja sokolov travel owns 4.1 pts, Vikram Mikhailov Travel 1.3 pts'),
    ).toBeInTheDocument()

    // No fetch at all -- the Why column came entirely from `finding.owns`,
    // already on the finding, no request needed to render it.
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('fetches /decompose only on Investigate -- zero requests before, exactly one after', async () => {
    const fetchMock = vi.fn((_input: RequestInfo | URL) =>
      jsonResponse({
        findingId: '1f4f6f672a4f',
        dim: 'VENDOR',
        overallObserved: 59.1,
        gap: 26.79,
        rows: [{ value: 'v1', label: 'Pooja Sokolov Travel', observed: 40, shareOfVolume: 30, pointsOfGap: 4.1, n: 50 }],
      }),
    )
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<PriorityActionCard finding={makeFinding()} runId="run-1" onDismiss={() => {}} />)

    expect(fetchMock).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: /investigate/i }))
    await screen.findByText('Pooja Sokolov Travel')

    const decomposeCalls = fetchMock.mock.calls.filter((call) => String(call[0]).includes('/decompose'))
    expect(decomposeCalls).toHaveLength(1)
  })

  it('expands to the evidence panel and decomposition table on Investigate', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        jsonResponse({
          findingId: '1f4f6f672a4f',
          dim: 'VENDOR',
          overallObserved: 59.1,
          gap: 26.79,
          rows: [{ value: 'v1', label: 'Pooja Sokolov Travel', observed: 40, shareOfVolume: 30, pointsOfGap: 4.1, n: 50 }],
        }),
      ),
    )
    const user = userEvent.setup()
    render(<PriorityActionCard finding={makeFinding()} runId="run-1" onDismiss={() => {}} />)

    expect(screen.queryByText(/SELECT/)).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /investigate/i }))

    expect(screen.getByText(/SELECT/)).toBeInTheDocument()
    expect(await screen.findByText('Pooja Sokolov Travel')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /investigate/i })).toHaveAttribute('aria-expanded', 'true')
  })

  it('Dismiss hides the card (via onDismiss) and persists to localStorage', async () => {
    vi.stubGlobal('fetch', vi.fn(() => notFound()))
    const onDismiss = vi.fn()
    const user = userEvent.setup()
    render(<PriorityActionCard finding={makeFinding()} runId="run-1" onDismiss={onDismiss} />)

    await user.click(screen.getByRole('button', { name: /dismiss/i }))

    expect(onDismiss).toHaveBeenCalledWith('1f4f6f672a4f')
    expect(JSON.parse(window.localStorage.getItem('signal-desk:dismissed-findings') ?? '[]')).toContain(
      '1f4f6f672a4f',
    )
  })

  it('Escalate posts to dispatch with FACILITIES_HEAD and shows channel results inline', async () => {
    const dispatchResponse: DispatchResponse = {
      runId: 'run-1',
      dispatched: [
        {
          audience: 'FACILITIES_HEAD',
          tier: 'BREACH',
          findingIds: ['1f4f6f672a4f'],
          channels: [{ channel: 'slack', delivered: true, detail: 'ok' }],
        },
      ],
    }
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/api/dispatch/')) return jsonResponse(dispatchResponse)
      return notFound()
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<PriorityActionCard finding={makeFinding()} runId="run-1" onDismiss={() => {}} />)

    await user.click(screen.getByRole('button', { name: /escalate/i }))

    expect(await screen.findByText(/Slack · delivered/)).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/dispatch/run-1'),
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ audiences: ['FACILITIES_HEAD'] }),
      }),
    )
  })
})
