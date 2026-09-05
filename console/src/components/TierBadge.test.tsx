import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { TierBadge } from './TierBadge.tsx'

describe('TierBadge', () => {
  it('encodes severity as a text label, not colour alone', () => {
    render(<TierBadge tier="BREACH" />)

    // The tier word must be present as real text content, independent of
    // whatever colour the stripe carries -- a screen reader or a washed-out
    // projector must still be able to tell BREACH from PASS. Rendered in
    // Title Case ("Breach"), per the UI-friendly-label rule -- the raw
    // enum value never reaches the screen.
    expect(screen.getByText('Breach')).toBeInTheDocument()
  })

  it('renders a different word per tier', () => {
    const { rerender } = render(<TierBadge tier="PASS" />)
    expect(screen.getByText('Pass')).toBeInTheDocument()

    rerender(<TierBadge tier="WATCH" />)
    expect(screen.getByText('Watch')).toBeInTheDocument()

    rerender(<TierBadge tier="CONCERN" />)
    expect(screen.getByText('Concern')).toBeInTheDocument()
  })
})
