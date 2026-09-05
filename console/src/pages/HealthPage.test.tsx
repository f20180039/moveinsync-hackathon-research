import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { FeedHealth } from '../api/types.ts'
import { HealthPage } from './HealthPage.tsx'

function makeFeed(overrides: Partial<FeedHealth>): FeedHealth {
  return {
    feed: 'bill',
    rowsLoaded: 3059,
    rowsRejected: 0,
    unmatchedKeys: 25,
    nullCriticalFields: 617,
    confidence: 0.79,
    mustBeDisclosed: true,
    ...overrides,
  }
}

describe('HealthPage', () => {
  it('renders the quirks section for a feed that carries one', () => {
    const feeds: FeedHealth[] = [
      makeFeed({
        quirks: [{ name: 'Slab-billed lines with no distance', rows: 247914, detail: '₹380.6M, 45% of spend' }],
      }),
    ]

    render(<HealthPage feeds={feeds} />)

    expect(screen.getByText('What we noticed and handled')).toBeInTheDocument()
    expect(screen.getByText('Slab-billed lines with no distance')).toBeInTheDocument()
    // en-IN grouping, deliberately (see HealthPage.tsx) -- not the raw
    // Western "247,914".
    expect(screen.getByText(/2,47,914 rows/)).toBeInTheDocument()
    expect(screen.getByText(/₹380\.6M, 45% of spend/)).toBeInTheDocument()
  })

  it('renders nothing for the quirks section when a feed has quirks: []', () => {
    const feeds: FeedHealth[] = [makeFeed({ quirks: [] })]

    render(<HealthPage feeds={feeds} />)

    expect(screen.queryByText('What we noticed and handled')).not.toBeInTheDocument()
  })

  it('renders nothing for the quirks section when no feed has a quirks key at all', () => {
    const feeds: FeedHealth[] = [makeFeed({})]
    // Simulate an older service response with no `quirks` field present.
    delete (feeds[0] as Partial<FeedHealth>).quirks

    render(<HealthPage feeds={feeds} />)

    expect(screen.queryByText('What we noticed and handled')).not.toBeInTheDocument()
  })
})
