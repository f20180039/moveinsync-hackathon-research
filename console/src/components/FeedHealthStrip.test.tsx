import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import fixture from '../../../handoff/fake-findings.json'
import type { FeedHealth } from '../api/types.ts'
import { FeedHealthStrip } from './FeedHealthStrip.tsx'

const fixtureFeeds = fixture.feedHealth as FeedHealth[]

// Deliberately NOT the fixture: every feed in the frozen fixture has
// rowsRejected: 0, so no test built against it alone can ever exercise (or
// break) the quarantined-count cell. Two feeds, two distinctive nonzero
// quarantined counts that don't collide with any other number in either row.
const quarantineFeeds: FeedHealth[] = [
  {
    feed: 'alpha',
    rowsLoaded: 500,
    rowsRejected: 1204,
    unmatchedKeys: 3,
    nullCriticalFields: 0,
    confidence: 0.95,
    mustBeDisclosed: false,
  },
  {
    feed: 'beta',
    rowsLoaded: 811,
    rowsRejected: 37,
    unmatchedKeys: 9,
    nullCriticalFields: 0,
    confidence: 0.93,
    mustBeDisclosed: false,
  },
]

describe('FeedHealthStrip', () => {
  it('shows quarantined rows as a number rather than hiding them', () => {
    render(<FeedHealthStrip feeds={quarantineFeeds} />)

    const alphaRow = screen.getByRole('row', { name: /alpha/i })
    expect(within(alphaRow).getByTestId('quarantined-count')).toHaveTextContent('1204')

    const betaRow = screen.getByRole('row', { name: /beta/i })
    expect(within(betaRow).getByTestId('quarantined-count')).toHaveTextContent('37')
  })

  it('flags a feed whose confidence is below 0.9', () => {
    render(<FeedHealthStrip feeds={fixtureFeeds} />)

    // alerts sits at 0.6335 confidence in the fixture.
    const alertsRow = screen.getByRole('row', { name: /alerts/i })
    expect(alertsRow).toHaveTextContent('⚠ low confidence')

    // trips sits at 0.9865 confidence and mustBeDisclosed: false -- must not
    // be flagged.
    const tripsRow = screen.getByRole('row', { name: /trips/i })
    expect(tripsRow).not.toHaveTextContent('⚠ low confidence')
  })

  it('flags a feed via mustBeDisclosed even when confidence is at or above 0.9', () => {
    const feeds: FeedHealth[] = [
      {
        feed: 'gamma',
        rowsLoaded: 900,
        rowsRejected: 0,
        unmatchedKeys: 0,
        nullCriticalFields: 0,
        confidence: 0.97, // well above the 0.9 threshold on its own
        mustBeDisclosed: true, // but the server says disclose it anyway
      },
    ]
    render(<FeedHealthStrip feeds={feeds} />)

    const gammaRow = screen.getByRole('row', { name: /gamma/i })
    expect(gammaRow).toHaveTextContent('⚠ low confidence')
  })
})
