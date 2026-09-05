import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { TopBar } from './TopBar.tsx'

function renderTopBar(
  overrides: Partial<React.ComponentProps<typeof TopBar>> = {},
  route = '/findings',
) {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <TopBar
        runId="run-1"
        windowLabel="2026-07-25..2026-07-31"
        onSweep={() => {}}
        sweeping={false}
        role="TRANSPORT_MANAGER"
        onRoleChange={() => {}}
        {...overrides}
      />
    </MemoryRouter>,
  )
}

describe('TopBar', () => {
  it('titles the page with the current nav item, not the run id', () => {
    renderTopBar({}, '/findings')

    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Insights')
  })

  it('follows the route, so the heading and the sidebar can never disagree', () => {
    renderTopBar({}, '/vendors')

    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Vendors')
  })

  it('still shows the run and its window, as provenance rather than as the title', () => {
    renderTopBar()

    const provenance = screen.getByText(/2026-07-25\.\.2026-07-31/)
    expect(provenance).toHaveTextContent('run-1')
    expect(provenance.tagName).not.toBe('H1')
  })

  it('shows a loading placeholder before the run is known', () => {
    renderTopBar({ runId: null, windowLabel: null })

    expect(screen.getByText(/loading/i)).toBeInTheDocument()
  })

  it('calls onSweep when Sweep now is pressed', async () => {
    const onSweep = vi.fn()
    renderTopBar({ onSweep })

    screen.getByRole('button', { name: /sweep now/i }).click()

    expect(onSweep).toHaveBeenCalledOnce()
  })

  it('shows the busy state while sweeping', () => {
    renderTopBar({ sweeping: true })

    expect(screen.getByRole('button', { name: /sweep now/i })).toHaveAttribute('aria-busy', 'true')
  })

  it('shows a "Viewing as" role switcher with all three roles', () => {
    renderTopBar()

    const select = screen.getByLabelText(/viewing as/i)
    expect(select).toHaveValue('TRANSPORT_MANAGER')
    expect(screen.getByRole('option', { name: 'Transport manager' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Transport & facilities head' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Line manager' })).toBeInTheDocument()
  })

  it('calls onRoleChange when a different role is selected', async () => {
    const onRoleChange = vi.fn()
    const user = userEvent.setup()
    renderTopBar({ onRoleChange })

    await user.selectOptions(screen.getByLabelText(/viewing as/i), 'FACILITIES_HEAD')

    expect(onRoleChange).toHaveBeenCalledWith('FACILITIES_HEAD')
  })
})
