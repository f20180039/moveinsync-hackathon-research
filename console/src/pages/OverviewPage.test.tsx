import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import fixture from '../../../handoff/fake-findings.json'
import type { Finding } from '../api/types.ts'
import { OverviewPage } from './OverviewPage.tsx'

const findings = fixture.findings as Finding[]
const baseFinding = findings[0]

function notFound() {
  return Promise.resolve({ ok: false, status: 404, statusText: 'Not Found', text: async () => '' } as Response)
}

function decomposeCallsFrom(fetchMock: { mock: { calls: unknown[][] } }): unknown[] {
  return fetchMock.mock.calls.filter((call) => String(call[0]).includes('/decompose'))
}

afterEach(() => {
  vi.unstubAllGlobals()
  window.localStorage.clear()
})

function renderOverview() {
  return render(
    <MemoryRouter>
      <OverviewPage windowLabel={fixture.windowLabel} runId={fixture.runId} findings={findings} />
    </MemoryRouter>,
  )
}

describe('OverviewPage', () => {
  it('renders the priority action cards using finding.owns, with zero /decompose requests', async () => {
    const fetchMock = vi.fn(() => notFound())
    vi.stubGlobal('fetch', fetchMock)

    renderOverview()
    const alertCount = findings.filter((f) => f.tier === 'CONCERN' || f.tier === 'BREACH').length
    const investigateButtons = await screen.findAllByRole('button', { name: /investigate/i })
    expect(investigateButtons).toHaveLength(Math.min(alertCount, 5))

    expect(decomposeCallsFrom(fetchMock)).toHaveLength(0)
  })

  it('fetches /decompose exactly once after clicking Investigate on one card (zero before)', async () => {
    const fetchMock = vi.fn(() => notFound())
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()

    renderOverview()
    await screen.findAllByRole('button', { name: /investigate/i })

    expect(decomposeCallsFrom(fetchMock)).toHaveLength(0)

    const [firstInvestigate] = screen.getAllByRole('button', { name: /investigate/i })
    await user.click(firstInvestigate)

    expect(decomposeCallsFrom(fetchMock)).toHaveLength(1)
  })

  it('accepts role-driven overrides: a KPI strip label, a role-specific KPI set, and a narrower priority-finding rule', async () => {
    vi.stubGlobal('fetch', vi.fn(() => notFound()))

    const { container } = render(
      <MemoryRouter>
        <OverviewPage
          windowLabel={fixture.windowLabel}
          runId={fixture.runId}
          findings={findings}
          kpiMetricIds={['ota', 'cost_per_rider']}
          kpiStripLabel="Cost · Safety · Experience"
          isPriorityFinding={(finding) => finding.tier === 'BREACH'}
        />
      </MemoryRouter>,
    )

    expect(screen.getByText('Cost · Safety · Experience')).toBeInTheDocument()
    const kpiRow = container.querySelector('.kpi-row') as HTMLElement
    expect(kpiRow).toHaveTextContent('Cost per rider')
    expect(kpiRow).not.toHaveTextContent('On-time departure')

    const breachCount = findings.filter((f) => f.tier === 'BREACH').length
    const investigateButtons = await screen.findAllByRole('button', { name: /investigate/i })
    expect(investigateButtons).toHaveLength(Math.min(breachCount, 5))
  })
})

// Regression: the role's findings filter is about which findings a role
// TRIAGES, not about what the overall number IS. Applied to the KPI row it
// starved every card, because no shift-sliced finding is the "overall" one.
describe('OverviewPage KPI cards vs the role findings filter', () => {
  it('renders KPI values from the unfiltered run, not the role-filtered list', () => {
    const overall: Finding = {
      ...baseFinding,
      id: 'f-overall-cost',
      metricId: 'cost_per_km',
      sliceLabel: 'overall',
      observed: 85.45,
      unit: 'INR/km',
      tier: 'PASS',
    }
    const shiftSliced: Finding = {
      ...baseFinding,
      id: 'f-shift',
      metricId: 'cost_per_km',
      sliceLabel: 'shift DAY',
      observed: 94.98,
      unit: 'INR/km',
      tier: 'WATCH',
    }

    render(
      <MemoryRouter>
        <OverviewPage
          windowLabel="2026-07-25..2026-07-31"
          runId="run-1"
          // What a Line manager sees: shift-sliced findings only.
          findings={[shiftSliced]}
          kpiFindings={[overall, shiftSliced]}
          kpiMetricIds={['cost_per_km']}
        />
      </MemoryRouter>,
    )

    expect(screen.queryByText('Not active yet')).not.toBeInTheDocument()
  })
})
