import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Legend } from './Legend.tsx'

afterEach(() => {
  vi.restoreAllMocks()
  window.localStorage.clear()
})

describe('Legend', () => {
  it('opens automatically on a first visit and renders all four tier names', () => {
    render(<Legend />)

    const dialog = screen.getByRole('dialog', { name: /how to read this/i })
    expect(dialog).toBeVisible()
    expect(screen.getByText('Pass')).toBeInTheDocument()
    expect(screen.getByText('Watch')).toBeInTheDocument()
    expect(screen.getByText('Concern')).toBeInTheDocument()
    expect(screen.getByText('Breach')).toBeInTheDocument()
  })

  it('moves focus inside the dialog when it opens', async () => {
    const user = userEvent.setup()
    render(<Legend />)

    // Auto-opened on mount (first visit).
    const dialog = screen.getByRole('dialog')
    expect(dialog.contains(document.activeElement)).toBe(true)

    // Also true for a user-initiated reopen, not just the automatic one.
    await user.click(screen.getByRole('button', { name: /close/i }))
    await user.click(screen.getByRole('button', { name: /how to read this/i }))
    expect(screen.getByRole('dialog').contains(document.activeElement)).toBe(true)
  })

  it('closes on the Close button and returns focus to the trigger', async () => {
    const user = userEvent.setup()
    render(<Legend />)

    const trigger = screen.getByRole('button', { name: /how to read this/i })
    await user.click(screen.getByRole('button', { name: /close/i }))

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
  })

  it('closes on Escape', async () => {
    const user = userEvent.setup()
    render(<Legend />)

    expect(screen.getByRole('dialog')).toBeVisible()
    await user.keyboard('{Escape}')

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('closes on a backdrop click', async () => {
    const user = userEvent.setup()
    render(<Legend />)

    const dialog = screen.getByRole('dialog')
    // A click on the <dialog> element itself (not its inner panel) is a
    // backdrop click.
    await user.click(dialog)

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('does not reopen automatically once the visitor has closed it', async () => {
    const user = userEvent.setup()
    const { unmount } = render(<Legend />)

    await user.click(screen.getByRole('button', { name: /close/i }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    unmount()

    // A later visit (a fresh mount) -- localStorage now remembers it was seen.
    render(<Legend />)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /how to read this/i })).toBeInTheDocument()
  })

  it('does not crash when localStorage throws, and still opens on first visit', () => {
    vi.spyOn(window.localStorage.__proto__, 'getItem').mockImplementation(() => {
      throw new Error('storage disabled')
    })

    expect(() => render(<Legend />)).not.toThrow()
    expect(screen.getByRole('dialog')).toBeVisible()
  })
})
