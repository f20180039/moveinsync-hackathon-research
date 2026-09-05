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

  it('gives Breach and Concern the strong (saturated) class, Watch and Pass the muted one', () => {
    const { container, rerender } = render(<TierBadge tier="BREACH" />)
    expect(container.querySelector('.tier-badge')?.classList.contains('tier-badge--strong')).toBe(true)

    rerender(<TierBadge tier="CONCERN" />)
    expect(container.querySelector('.tier-badge')?.classList.contains('tier-badge--strong')).toBe(true)

    rerender(<TierBadge tier="WATCH" />)
    expect(container.querySelector('.tier-badge')?.classList.contains('tier-badge--muted')).toBe(true)

    rerender(<TierBadge tier="PASS" />)
    expect(container.querySelector('.tier-badge')?.classList.contains('tier-badge--muted')).toBe(true)
  })

  it('renders a distinct icon alongside the tier word for all four tiers', () => {
    const { container, rerender } = render(<TierBadge tier="BREACH" />)
    expect(container.querySelector('.tier-badge__icon')).toBeInTheDocument()
    expect(screen.getByText('Breach')).toBeInTheDocument()

    for (const tier of ['CONCERN', 'WATCH', 'PASS'] as const) {
      rerender(<TierBadge tier={tier} />)
      expect(container.querySelector('.tier-badge__icon')).toBeInTheDocument()
    }
  })
})
