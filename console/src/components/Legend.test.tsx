import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Legend } from './Legend.tsx'

afterEach(() => {
  vi.restoreAllMocks()
  window.localStorage.clear()
})

describe('Legend', () => {
  it('renders all four tier names', () => {
    render(<Legend />)

    expect(screen.getByText('PASS')).toBeInTheDocument()
    expect(screen.getByText('WATCH')).toBeInTheDocument()
    expect(screen.getByText('CONCERN')).toBeInTheDocument()
    expect(screen.getByText('BREACH')).toBeInTheDocument()
  })

  it('is open by default and collapses/expands on toggle', async () => {
    const user = userEvent.setup()
    render(<Legend />)

    // Open by default on a first visit -- the body content is visible.
    expect(screen.getByText(/one model call per brief/)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /hide/i }))
    expect(screen.queryByText(/one model call per brief/)).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /show/i }))
    expect(screen.getByText(/one model call per brief/)).toBeInTheDocument()
  })

  it('honours a stored collapsed state', () => {
    vi.spyOn(window.localStorage.__proto__, 'getItem').mockReturnValue('true')

    render(<Legend />)

    expect(screen.queryByText(/one model call per brief/)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /show/i })).toBeInTheDocument()
  })

  it('does not crash when localStorage throws', () => {
    vi.spyOn(window.localStorage.__proto__, 'getItem').mockImplementation(() => {
      throw new Error('storage disabled')
    })

    expect(() => render(<Legend />)).not.toThrow()
    // Safe default when storage is unavailable: open.
    expect(screen.getByText(/one model call per brief/)).toBeInTheDocument()
  })
})
