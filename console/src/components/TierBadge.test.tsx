import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { TierBadge } from './TierBadge.tsx'

describe('TierBadge', () => {
  it('encodes severity as a text label, not colour alone', () => {
    render(<TierBadge tier="BREACH" />)

    // The tier word must be present as real text content, independent of
    // whatever colour the stripe carries -- a screen reader or a washed-out
    // projector must still be able to tell BREACH from PASS.
    expect(screen.getByText('BREACH')).toBeInTheDocument()
  })

  it('renders a different word per tier', () => {
    const { rerender } = render(<TierBadge tier="PASS" />)
    expect(screen.getByText('PASS')).toBeInTheDocument()

    rerender(<TierBadge tier="WATCH" />)
    expect(screen.getByText('WATCH')).toBeInTheDocument()

    rerender(<TierBadge tier="CONCERN" />)
    expect(screen.getByText('CONCERN')).toBeInTheDocument()
  })
})
