import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { TopBar } from './TopBar.tsx'

describe('TopBar', () => {
  it('shows the run id and window label', () => {
    render(<TopBar runId="run-1" windowLabel="2026-07-25..2026-07-31" onSweep={() => {}} sweeping={false} />)

    expect(screen.getByText(/2026-07-25\.\.2026-07-31/)).toBeInTheDocument()
    expect(screen.getByText(/run-1/)).toBeInTheDocument()
  })

  it('shows a loading placeholder before the run is known', () => {
    render(<TopBar runId={null} windowLabel={null} onSweep={() => {}} sweeping={false} />)

    expect(screen.getByText(/loading/i)).toBeInTheDocument()
  })

  it('calls onSweep when Sweep now is pressed', async () => {
    const onSweep = vi.fn()
    render(<TopBar runId="run-1" windowLabel="window" onSweep={onSweep} sweeping={false} />)

    screen.getByRole('button', { name: /sweep now/i }).click()

    expect(onSweep).toHaveBeenCalledOnce()
  })

  it('shows the busy state while sweeping', () => {
    render(<TopBar runId="run-1" windowLabel="window" onSweep={() => {}} sweeping={true} />)

    expect(screen.getByRole('button', { name: /sweep now/i })).toHaveAttribute('aria-busy', 'true')
  })
})
