import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { Sidebar } from './Sidebar.tsx'
import type { AlertSeverity } from './Sidebar.tsx'

const ALL_LABELS = [
  'Overview',
  'Alerts',
  'Insights',
  'Vendors',
  'Data health',
  'Cost',
  'Weekly review',
  'Monthly review',
  'Brief & dispatch',
]

function renderSidebar(initialEntries: string[] = ['/'], alertCount = 0, alertSeverity: AlertSeverity = null) {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <Sidebar alertCount={alertCount} alertSeverity={alertSeverity} />
    </MemoryRouter>,
  )
}

describe('Sidebar', () => {
  it("gives every nav link an accessible name equal to its label, regardless of the collapse media query", () => {
    renderSidebar()

    // display:none (used under 1024px) would strip this text from the
    // accessibility tree; the `aria-label` on each NavLink holds the name
    // fixed either way, which is exactly what this asserts.
    for (const label of ALL_LABELS) {
      expect(screen.getByRole('link', { name: label })).toBeInTheDocument()
    }
  })

  it('marks the current route active (aria-current + active class), and nothing else', () => {
    renderSidebar(['/alerts'])

    const alertsLink = screen.getByRole('link', { name: 'Alerts' })
    expect(alertsLink).toHaveAttribute('aria-current', 'page')
    expect(alertsLink.classList.contains('sidebar__link--active')).toBe(true)

    const overviewLink = screen.getByRole('link', { name: 'Overview' })
    expect(overviewLink).not.toHaveAttribute('aria-current')
    expect(overviewLink.classList.contains('sidebar__link--active')).toBe(false)
  })

  it('shows the alert count as a badge when there are unread alerts', () => {
    renderSidebar(['/'], 3, 'breach')

    expect(screen.getByRole('link', { name: 'Alerts' })).toHaveTextContent('3')
  })

  it('shows no badge when there are no alerts', () => {
    renderSidebar(['/'], 0, null)

    expect(screen.getByRole('link', { name: 'Alerts' })).not.toHaveTextContent(/\d/)
  })

  it('colours the badge red when a Breach exists, amber when only Concern does', () => {
    const { container, rerender } = render(
      <MemoryRouter>
        <Sidebar alertCount={2} alertSeverity="breach" />
      </MemoryRouter>,
    )
    expect(container.querySelector('.sidebar__badge')?.classList.contains('sidebar__badge--breach')).toBe(true)

    rerender(
      <MemoryRouter>
        <Sidebar alertCount={1} alertSeverity="concern" />
      </MemoryRouter>,
    )
    expect(container.querySelector('.sidebar__badge')?.classList.contains('sidebar__badge--concern')).toBe(true)
  })

  it('only links a path when it is in visibleNavPaths -- a route not listed is simply not linked, not a 403', () => {
    render(
      <MemoryRouter>
        <Sidebar alertCount={0} alertSeverity={null} visibleNavPaths={new Set(['/', '/alerts', '/brief'])} />
      </MemoryRouter>,
    )

    expect(screen.getByRole('link', { name: 'Overview' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Alerts' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Brief & dispatch' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Insights' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Vendors' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Data health' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Cost' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Weekly review' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Monthly review' })).not.toBeInTheDocument()
  })
})
