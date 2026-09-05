import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { Finding } from '../api/types.ts'
import { RecurringTag } from './RecurringTag.tsx'

function makeFinding(overrides: Partial<Finding>): Finding {
  return {
    id: 'f1',
    metricId: 'marshal_compliance',
    metricLabel: 'Marshal compliance',
    unit: '%',
    sliceLabel: 'overall',
    tier: 'BREACH',
    cause: 'BELOW_TARGET',
    observed: 32,
    gap: 68,
    confidence: 0.96,
    audiences: ['TRANSPORT_MANAGER'],
    references: [],
    evidenceSql: 'SELECT 1',
    ...overrides,
  }
}

describe('RecurringTag', () => {
  it('renders nothing when recurrence is absent (feature-detected)', () => {
    const { container } = render(<RecurringTag finding={makeFinding({})} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('renders nothing at 2 of the last 4 weeks (below threshold)', () => {
    const { container } = render(<RecurringTag finding={makeFinding({ recurrence: { weeks: 2, of: 4 } })} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('renders the tag at 3 of the last 4 weeks', () => {
    render(<RecurringTag finding={makeFinding({ recurrence: { weeks: 3, of: 4 } })} />)
    expect(screen.getByText(/3 of the last 4 weeks/)).toBeInTheDocument()
  })

  it('renders the tag at 4 of 4', () => {
    render(<RecurringTag finding={makeFinding({ recurrence: { weeks: 4, of: 4 } })} />)
    expect(screen.getByText(/4 of the last 4 weeks/)).toBeInTheDocument()
  })

  it('the "short" variant abbreviates to "Recurring N/of", with the full sentence as the title', () => {
    render(<RecurringTag finding={makeFinding({ recurrence: { weeks: 3, of: 4 } })} variant="short" />)

    const tag = screen.getByText('Recurring 3/4')
    expect(tag).toBeInTheDocument()
    expect(tag).toHaveAttribute('title', 'Recurring · 3 of the last 4 weeks')
    // The long sentence must not appear as rendered text in this variant.
    expect(screen.queryByText(/of the last 4 weeks/)).not.toBeInTheDocument()
  })
})
