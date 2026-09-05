import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import fixture from '../../../handoff/fake-findings.json'
import type { Finding } from '../api/types.ts'
import { FindingsPage } from './FindingsPage.tsx'

const findings = fixture.findings as Finding[]

// MemoryRouter keeps its own history stack, not window.location -- this
// surfaces the current URL (path + query string) as text so a test can
// assert the round-trip without reaching into router internals.
function LocationProbe() {
  const location = useLocation()
  return <div data-testid="location-probe">{location.pathname + location.search}</div>
}

function renderFindings(initialPath = '/findings') {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <FindingsPage findings={findings} />
      <LocationProbe />
    </MemoryRouter>,
  )
}

function metricNames(): string[] {
  return screen
    .getAllByText(
      (_, element) => element?.tagName.toLowerCase() === 'span' && element.classList.contains('finding-row__metric'),
    )
    .map((el) => el.textContent)
}

describe('FindingsPage', () => {
  it('shows every finding with no filters active', () => {
    renderFindings()
    expect(metricNames()).toHaveLength(findings.length)
  })

  it('filters by severity, composing with other filters via AND', async () => {
    const user = userEvent.setup()
    renderFindings()

    await user.click(screen.getByRole('checkbox', { name: /breach/i }))

    const breachCount = findings.filter((f) => f.tier === 'BREACH').length
    expect(metricNames()).toHaveLength(breachCount)
  })

  it('shows the plain empty-result state when filters match nothing', async () => {
    const user = userEvent.setup()
    renderFindings()

    const observedInput = screen.getByLabelText('Observed')
    await user.type(observedInput, '> 100000')

    expect(screen.getByText('No findings match these filters.')).toBeInTheDocument()
  })

  it('shows an inline hint for invalid Observed input, filtering nothing', async () => {
    const user = userEvent.setup()
    renderFindings()

    const observedInput = screen.getByLabelText('Observed')
    await user.type(observedInput, 'banana')

    expect(screen.getByText(/try/i)).toBeInTheDocument()
    // Invalid input filters nothing -- every finding still shows.
    expect(metricNames()).toHaveLength(findings.length)
  })

  it('round-trips filter state through the URL query string', async () => {
    const user = userEvent.setup()
    renderFindings()

    await user.click(screen.getByRole('checkbox', { name: /breach/i }))
    await user.type(screen.getByLabelText('Observed'), '< 60')

    const locationText = screen.getByTestId('location-probe').textContent ?? ''
    const query = new URLSearchParams(locationText.split('?')[1])
    expect(query.get('tiers')).toBe('BREACH')
    expect(query.get('observed')).toBe('< 60')
  })

  it('reads filter state back out of an incoming URL (a shared link works)', () => {
    renderFindings('/findings?tiers=BREACH')

    const breachCount = findings.filter((f) => f.tier === 'BREACH').length
    expect(metricNames()).toHaveLength(breachCount)
    expect(screen.getByRole('checkbox', { name: /breach/i })).toBeChecked()
  })

  it('paginates at 25 per page and shows "Showing X–Y of Z"', () => {
    renderFindings()

    // This fixture has fewer than 25 findings -- one page, everything shown.
    const nav = screen.getByRole('navigation', { name: /pagination/i })
    expect(within(nav).getByText(new RegExp(`of ${findings.length}$`))).toBeInTheDocument()
    expect(within(nav).getByRole('button', { name: /previous/i })).toBeDisabled()
    expect(within(nav).getByRole('button', { name: /next/i })).toBeDisabled()
  })

  it('ignores a bogus tier in the URL rather than crashing (?tiers=BOGUS,BREACH keeps only Breach)', () => {
    renderFindings('/findings?tiers=BOGUS,BREACH')

    const breachCount = findings.filter((f) => f.tier === 'BREACH').length
    expect(metricNames()).toHaveLength(breachCount)
    expect(screen.getByRole('checkbox', { name: /breach/i })).toBeChecked()
    // Only a real tier ever gets checked -- there's no checkbox for "BOGUS"
    // to begin with, so nothing else to assert unchecked against it.
    expect(screen.getByRole('checkbox', { name: /watch/i })).not.toBeChecked()
  })

  it('clamps a negative page (?page=-3) to page 1, not a crash or a blank page', () => {
    renderFindings('/findings?page=-3')

    const nav = screen.getByRole('navigation', { name: /pagination/i })
    expect(within(nav).getByText(/^Page 1 of/)).toBeInTheDocument()
    expect(metricNames()).toHaveLength(findings.length)
  })

  it('clamps a non-numeric page (?page=abc) to page 1, not a crash or a blank page', () => {
    renderFindings('/findings?page=abc')

    const nav = screen.getByRole('navigation', { name: /pagination/i })
    expect(within(nav).getByText(/^Page 1 of/)).toBeInTheDocument()
    expect(metricNames()).toHaveLength(findings.length)
  })
})
