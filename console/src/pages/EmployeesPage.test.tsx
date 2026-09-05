import { render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { EmployeeImpact } from '../api/types.ts'
import { EmployeesPage } from './EmployeesPage.tsx'

function jsonResponse(body: unknown) {
  return Promise.resolve({ ok: true, json: async () => body } as Response)
}

function notFound() {
  return Promise.resolve({ ok: false, status: 404, statusText: 'Not Found', text: async () => '' } as Response)
}

function healthResponse(capabilities?: string[]) {
  return jsonResponse({
    status: 'ok',
    activeMetrics: ['ota'],
    clock: '2026-09-05T09:00:00Z',
    ...(capabilities !== undefined && { capabilities }),
  })
}

// Field names verbatim from service/signaldesk/api.py's
// get_employees_impact() -- if the service renames one, this fixture (and
// therefore these tests) is where it has to be changed.
function makeImpact(overrides: Partial<EmployeeImpact> = {}): EmployeeImpact {
  return {
    runId: 'run-1',
    window: { start: 1782864900000, end: 1783469700000, label: 'week of 1 July' },
    employeesImpacted: 1204,
    ridersInWindow: 8110,
    noShowLegs: 317,
    latePickupLegs: 2489,
    avgPickupDelayMin: 12.4,
    medianPickupDelayMin: 7.5,
    employeeCausedDelayShare: 0.0812,
    byShiftBand: [
      { shiftBand: 'NIGHT', legs: 4120, noShows: 190, latePickups: 1310, impacted: 622 },
      { shiftBand: 'EARLY', legs: 3011, noShows: 84, latePickups: 702, impacted: 341 },
    ],
    bySite: [{ site: 'Santa Clara Office', legs: 5200, noShows: 210, latePickups: 1502, impacted: 781 }],
    byVendor: [{ vendor: 'Rohan Mikhailov Travel', legs: 3980, noShows: 175, latePickups: 1204, impacted: 604 }],
    costPerRider: 214.6,
    costPerRiderTrend: 198.2,
    ...overrides,
  }
}

function stubFetch(routes: { health?: () => Promise<Response>; impact?: () => Promise<Response> }) {
  const fetchMock = vi.fn((input: RequestInfo | URL) => {
    const url = String(input)
    if (url.includes('/api/employees/impact')) return routes.impact?.() ?? notFound()
    if (url.includes('/api/health')) return routes.health?.() ?? notFound()
    return notFound()
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('EmployeesPage', () => {
  it('renders the headline figures and a row per shift band, site and vendor', async () => {
    stubFetch({
      health: () => healthResponse(['ask', 'employees']),
      impact: () => jsonResponse(makeImpact()),
    })

    const { container } = render(<EmployeesPage runId="run-1" />)

    await screen.findByText('of 8,110 riders in this window')
    // Scoped to the headline strip: the same figures also legitimately
    // appear inside the breakdown tables.
    const stats = within(container.querySelector('.impact-stats') as HTMLElement)
    expect(stats.getByText('1,204')).toBeInTheDocument() // employeesImpacted, en-IN
    expect(stats.getByText('2,489')).toBeInTheDocument() // latePickupLegs
    expect(stats.getByText('317')).toBeInTheDocument() // noShowLegs
    expect(stats.getByText('12.4 min')).toBeInTheDocument()
    expect(stats.getByText('median 7.5 min')).toBeInTheDocument()
    expect(stats.getByText('₹214.6')).toBeInTheDocument()
    expect(stats.getByText('4-week average ₹198.2')).toBeInTheDocument()
    expect(stats.getByText('8.1%')).toBeInTheDocument() // employeeCausedDelayShare

    // The shift band renders humanised, never as the raw NIGHT/EARLY code.
    const tables = container.querySelectorAll('.impact-table')
    expect(tables).toHaveLength(3)
    const shiftTable = within(tables[0] as HTMLElement)
    expect(shiftTable.getByRole('rowheader', { name: 'Night' })).toBeInTheDocument()
    expect(shiftTable.getByRole('rowheader', { name: 'Early' })).toBeInTheDocument()
    expect(shiftTable.getByText('622')).toBeInTheDocument()

    // Site and vendor names are proper nouns and render exactly as sent.
    expect(screen.getByRole('rowheader', { name: 'Santa Clara Office' })).toBeInTheDocument()
    expect(screen.getByRole('rowheader', { name: 'Rohan Mikhailov Travel' })).toBeInTheDocument()
  })

  it('renders rows in the order the service ranked them, never re-sorted', async () => {
    stubFetch({
      health: () => healthResponse(['employees']),
      impact: () =>
        jsonResponse(
          makeImpact({
            byShiftBand: [
              { shiftBand: 'DAY', legs: 10, noShows: 1, latePickups: 2, impacted: 3 },
              { shiftBand: 'NIGHT', legs: 99, noShows: 9, latePickups: 9, impacted: 90 },
            ],
          }),
        ),
    })

    const { container } = render(<EmployeesPage runId="run-1" />)
    await screen.findByRole('rowheader', { name: 'Day' })

    const rowHeaders = Array.from(
      (container.querySelector('.impact-table') as HTMLElement).querySelectorAll('tbody th'),
    ).map((th) => th.textContent)
    expect(rowHeaders).toEqual(['Day', 'Night'])
  })

  it('handles the empty case -- no legs measured, so no breakdown tables', async () => {
    stubFetch({
      health: () => healthResponse(['employees']),
      impact: () =>
        jsonResponse(
          makeImpact({
            employeesImpacted: 0,
            ridersInWindow: 0,
            noShowLegs: 0,
            latePickupLegs: 0,
            avgPickupDelayMin: null,
            medianPickupDelayMin: null,
            employeeCausedDelayShare: null,
            byShiftBand: [],
            bySite: [],
            byVendor: [],
            costPerRider: null,
            costPerRiderTrend: null,
          }),
        ),
    })

    const { container } = render(<EmployeesPage runId="run-1" />)

    expect(
      await screen.findByText(/no employee legs were measured for this window/i),
    ).toBeInTheDocument()
    expect(container.querySelectorAll('.impact-table')).toHaveLength(0)

    // A null reading renders the shared em-dash, never a "0 min" or "₹0"
    // that would read as a real measurement.
    expect(screen.getAllByText('—').length).toBeGreaterThan(0)
    expect(screen.queryByText('0 min')).not.toBeInTheDocument()
    expect(screen.queryByText('₹0')).not.toBeInTheDocument()
  })

  it('says the endpoint is absent when /api/health omits the "employees" capability -- and never calls it', async () => {
    const fetchMock = stubFetch({ health: () => healthResponse(['ask', 'decompose']) })

    render(<EmployeesPage runId="run-1" />)

    expect(await screen.findByText(/employee impact is not available on this build/i)).toBeInTheDocument()
    const impactCalls = fetchMock.mock.calls.filter(([input]) => String(input).includes('/api/employees/impact'))
    expect(impactCalls).toHaveLength(0)
  })

  it('still fetches when /api/health omits `capabilities` entirely (older service)', async () => {
    const fetchMock = stubFetch({
      health: () => healthResponse(undefined),
      impact: () => jsonResponse(makeImpact()),
    })

    render(<EmployeesPage runId="run-1" />)

    expect(await screen.findByText('of 8,110 riders in this window')).toBeInTheDocument()
    const impactCalls = fetchMock.mock.calls.filter(([input]) => String(input).includes('/api/employees/impact'))
    expect(impactCalls).toHaveLength(1)
  })

  it('shows the failure, not an "unavailable" page, when the endpoint itself errors', async () => {
    stubFetch({
      health: () => healthResponse(['employees']),
      impact: () =>
        Promise.resolve({ ok: false, status: 500, statusText: 'Server Error', text: async () => '' } as Response),
    })

    render(<EmployeesPage runId="run-1" />)

    expect(await screen.findByText(/500 Server Error/)).toBeInTheDocument()
    expect(screen.queryByText(/not available on this build/i)).not.toBeInTheDocument()
  })
})
