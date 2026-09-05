import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import fixture from '../../../handoff/fake-findings.json'
import type { Finding } from '../api/types.ts'
import { AlertsPage } from './AlertsPage.tsx'

const findings = fixture.findings as Finding[]

function notFound() {
  return Promise.resolve({ ok: false, status: 404, statusText: 'Not Found', text: async () => '' } as Response)
}

afterEach(() => {
  vi.unstubAllGlobals()
  window.localStorage.clear()
})

function renderAlerts() {
  return render(
    <MemoryRouter>
      <AlertsPage findings={findings} runId={fixture.runId} />
    </MemoryRouter>,
  )
}

describe('AlertsPage', () => {
  it('renders a priority-action card for every CONCERN/BREACH finding, not just the top 5', async () => {
    vi.stubGlobal('fetch', vi.fn(() => notFound()))

    renderAlerts()

    const alertCount = findings.filter((f) => f.tier === 'CONCERN' || f.tier === 'BREACH').length
    expect(alertCount).toBeGreaterThan(5) // this fixture has more than 5 -- proves "all", not "top 5"
    expect(screen.getAllByRole('button', { name: /investigate/i })).toHaveLength(alertCount)
  })

  it('Dismiss removes a card from the Alerts list', async () => {
    vi.stubGlobal('fetch', vi.fn(() => notFound()))
    const user = userEvent.setup()

    renderAlerts()

    const alertCount = findings.filter((f) => f.tier === 'CONCERN' || f.tier === 'BREACH').length
    const dismissButtons = screen.getAllByRole('button', { name: /dismiss/i })
    await user.click(dismissButtons[0])

    expect(screen.getAllByRole('button', { name: /investigate/i })).toHaveLength(alertCount - 1)
  })
})
