import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import fixture from '../../../handoff/fake-findings.json'
import type { Finding } from '../api/types.ts'
import { OverviewPage } from './OverviewPage.tsx'

const findings = fixture.findings as Finding[]

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
    // Let the (unrelated) AskBar mount-time /api/ask probe settle, inside
    // act, before asserting -- it is not what this test is about.
    await screen.findByText('Interrogation lands with the tools — coming')

    const alertCount = findings.filter((f) => f.tier === 'CONCERN' || f.tier === 'BREACH').length
    const investigateButtons = screen.getAllByRole('button', { name: /investigate/i })
    expect(investigateButtons).toHaveLength(Math.min(alertCount, 5))

    expect(decomposeCallsFrom(fetchMock)).toHaveLength(0)
  })

  it('fetches /decompose exactly once after clicking Investigate on one card (zero before)', async () => {
    const fetchMock = vi.fn(() => notFound())
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()

    renderOverview()
    await screen.findByText('Interrogation lands with the tools — coming')

    expect(decomposeCallsFrom(fetchMock)).toHaveLength(0)

    const [firstInvestigate] = screen.getAllByRole('button', { name: /investigate/i })
    await user.click(firstInvestigate)

    expect(decomposeCallsFrom(fetchMock)).toHaveLength(1)
  })
})
