import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import fixture from '../../../handoff/fake-findings.json'
import type { FeedHealth } from '../api/types.ts'
import { FeedHealthStrip } from './FeedHealthStrip.tsx'

const feeds = fixture.feedHealth as FeedHealth[]

describe('FeedHealthStrip', () => {
  it('shows quarantined rows as a number rather than hiding them', () => {
    render(<FeedHealthStrip feeds={feeds} />)

    // `bill` has 617 nullCriticalFields and 25 unmatchedKeys in the fixture --
    // unmatched must be a visible number, not tucked into a tooltip.
    const billRow = screen.getByRole('row', { name: /bill/ })
    expect(billRow).toHaveTextContent('25')
  })

  it('flags a feed whose confidence is below 0.9', () => {
    render(<FeedHealthStrip feeds={feeds} />)

    // alerts sits at 0.6335 confidence in the fixture.
    const alertsRow = screen.getByRole('row', { name: /alerts/ })
    expect(alertsRow).toHaveTextContent('⚠ low confidence')

    // trips sits at 0.9865 confidence -- must not be flagged.
    const tripsRow = screen.getByRole('row', { name: /trips/ })
    expect(tripsRow).not.toHaveTextContent('⚠ low confidence')
  })
})
