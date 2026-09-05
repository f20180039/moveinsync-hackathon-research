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

  it('carries the page title and nothing else -- no run/window provenance line', () => {
    const { container } = renderTopBar()

    expect(container.querySelector('.top-bar__run')).toBeNull()
    expect(container.querySelector('.top-bar__heading')).toHaveTextContent('Insights')
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

  it('shows a "Viewing as" role switcher with the two shipped personas', () => {
    renderTopBar()

    const select = screen.getByLabelText(/viewing as/i)
    expect(select).toHaveValue('TRANSPORT_MANAGER')
    expect(screen.getByRole('option', { name: 'Transport manager' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Transport & facilities head' })).toBeInTheDocument()
    // Line manager is an audience the service routes to, not a persona
    // the console offers -- see roles.ts.
    expect(screen.queryByRole('option', { name: 'Line manager' })).not.toBeInTheDocument()
  })

  it('calls onRoleChange when a different role is selected', async () => {
    const onRoleChange = vi.fn()
    const user = userEvent.setup()
    renderTopBar({ onRoleChange })

    await user.selectOptions(screen.getByLabelText(/viewing as/i), 'FACILITIES_HEAD')

    expect(onRoleChange).toHaveBeenCalledWith('FACILITIES_HEAD')
  })
})
