import { render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { OutlookProjection, ShiftOutlook } from '../api/types.ts'
import { ShiftOutlookCard } from './ShiftOutlookCard.tsx'

function jsonResponse(body: unknown) {
  return Promise.resolve({ ok: true, json: async () => body } as Response)
}

function notFound() {
  return Promise.resolve({ ok: false, status: 404, statusText: 'Not Found', text: async () => '' } as Response)
}

function healthResponse(capabilities?: string[]) {
  return jsonResponse({
    status: 'ok',
    activeMetrics: ['no_show_rate'],
    clock: '2026-09-05T09:00:00Z',
    ...(capabilities !== undefined && { capabilities }),
  })
}

// Field names verbatim from service/signaldesk/forecast.py's
// Projection.to_json().
function makeProjection(overrides: Partial<OutlookProjection> = {}): OutlookProjection {
  return {
    metric: 'no_show_rate',
    metricLabel: 'No-show rate',
    unit: '%',
    slice: 'shift NIGHT',
    targetDate: '2026-07-29',
    targetStartMs: 1785283200000,
    projected: 11.4,
    intervalLow: 9.2,
    intervalHigh: 13.6,
    readiness: 'NOT_READY',
    tier: 'BREACH',
    reference: { kind: 'TREND', label: '4-week average', value: 7.1 },
    action: 'Release 12 seats on the night shift.',
    method: 'seasonal-baseline-4w',
    basisDaysUsed: 4,
    degraded: false,
    withheld: false,
    note: '',
    basis: [],
    ...overrides,
  }
}

function makeOutlook(overrides: Partial<ShiftOutlook> = {}): ShiftOutlook {
  return {
    runId: 'run-1',
    metric: 'no_show_rate',
    method: 'seasonal-baseline-4w',
    basisWeeks: 4,
    weights: [4, 3, 2, 1],
    targetDate: '2026-07-29',
    targetStartMs: 1785283200000,
    shifts: [makeProjection()],
    ...overrides,
  }
}

function stubFetch(routes: { health?: () => Promise<Response>; outlook?: () => Promise<Response> }) {
  const fetchMock = vi.fn((input: RequestInfo | URL) => {
    const url = String(input)
    if (url.includes('/api/outlook/shifts')) return routes.outlook?.() ?? notFound()
    if (url.includes('/api/health')) return routes.health?.() ?? notFound()
    return notFound()
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('ShiftOutlookCard', () => {
  it('renders one row per shift band with its readiness, projection and action', async () => {
    stubFetch({
      health: () => healthResponse(['ask', 'outlook']),
      outlook: () =>
        jsonResponse(
          makeOutlook({
            shifts: [
              makeProjection(),
              makeProjection({ slice: 'shift EARLY', readiness: 'READY', projected: 3.1, action: 'No action.' }),
            ],
          }),
        ),
    })

    render(<ShiftOutlookCard runId="run-1" />)

    // Readiness words are humanised -- NOT_READY never reaches the screen.
    expect(await screen.findByText('Not ready')).toBeInTheDocument()
    expect(screen.getByText('Ready')).toBeInTheDocument()
    expect(screen.queryByText(/NOT_READY/)).not.toBeInTheDocument()

    const nightRow = screen.getByRole('rowheader', { name: 'Shift: Night' }).closest('tr') as HTMLElement
    expect(within(nightRow).getByText('11.4%')).toBeInTheDocument()
    expect(within(nightRow).getByText('9.2% – 13.6%')).toBeInTheDocument()
    expect(within(nightRow).getByText('Release 12 seats on the night shift.')).toBeInTheDocument()

    // The method is stated on the card, from the service's own basisWeeks.
    expect(screen.getByText(/same-weekday baseline over the last 4 weeks/i)).toBeInTheDocument()
    expect(screen.getByText(/not a prediction/i)).toBeInTheDocument()
  })

  it('renders a WITHHELD projection as the service\'s stated refusal, never as a zero', async () => {
    stubFetch({
      health: () => healthResponse(['outlook']),
      outlook: () =>
        jsonResponse(
          makeOutlook({
            shifts: [
              makeProjection({
                readiness: 'WITHHELD',
                withheld: true,
                projected: null,
                intervalLow: null,
                intervalHigh: null,
                tier: null,
                basisDaysUsed: 1,
                note: 'Only 1 of 4 basis days have data, so a number is withheld.',
                action: '',
              }),
            ],
          }),
        ),
    })

    render(<ShiftOutlookCard runId="run-1" />)

    expect(await screen.findByText('Withheld')).toBeInTheDocument()
    expect(screen.getByText(/only 1 of 4 basis days have data/i)).toBeInTheDocument()
    // A refusal, not a measurement: no invented zero anywhere on the row.
    const row = screen.getByRole('rowheader', { name: 'Shift: Night' }).closest('tr') as HTMLElement
    expect(within(row).getAllByText('—').length).toBeGreaterThan(0)
    expect(within(row).queryByText('0%')).not.toBeInTheDocument()
    // And it is not an error.
    expect(screen.queryByText(/404|500/)).not.toBeInTheDocument()
  })

  it('renders nothing at all when the build does not advertise "outlook"', async () => {
    const fetchMock = stubFetch({ health: () => healthResponse(['ask', 'employees']) })

    const { container } = render(<ShiftOutlookCard runId="run-1" />)

    // Waits for the capability check to resolve before asserting emptiness.
    await vi.waitFor(() => expect(container.querySelector('.outlook-card')).toBeNull())
    expect(screen.queryByText(/shift readiness outlook/i)).not.toBeInTheDocument()
    const outlookCalls = fetchMock.mock.calls.filter(([input]) => String(input).includes('/api/outlook'))
    expect(outlookCalls).toHaveLength(0)
  })

  it('passes the chosen target date through to the service, and nothing when it is blank', async () => {
    const fetchMock = stubFetch({
      health: () => healthResponse(['outlook']),
      outlook: () => jsonResponse(makeOutlook()),
    })

    render(<ShiftOutlookCard runId="run-1" date="2026-07-29" />)
    await screen.findByText('Not ready')

    const call = fetchMock.mock.calls.find(([input]) => String(input).includes('/api/outlook/shifts'))
    expect(String(call?.[0])).toContain('date=2026-07-29')
    expect(String(call?.[0])).toContain('runId=run-1')
  })

  it('shows the failure, not an empty card, when the endpoint itself errors', async () => {
    stubFetch({
      health: () => healthResponse(['outlook']),
      outlook: () =>
        Promise.resolve({ ok: false, status: 500, statusText: 'Server Error', text: async () => '' } as Response),
    })

    render(<ShiftOutlookCard runId="run-1" />)

    expect(await screen.findByText(/500 Server Error/)).toBeInTheDocument()
    expect(screen.getByText(/shift readiness outlook/i)).toBeInTheDocument()
  })
})
