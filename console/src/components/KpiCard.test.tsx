import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { Finding } from '../api/types.ts'
import { KpiCard } from './KpiCard.tsx'

function makeFinding(overrides: Partial<Finding>): Finding {
  return {
    id: 'f1',
    metricId: 'ota',
    metricLabel: 'On-time arrival',
    unit: '%',
    sliceLabel: 'overall',
    tier: 'BREACH',
    cause: 'BELOW_TARGET',
    observed: 59.1,
    gap: 30.9,
    confidence: 0.96,
    audiences: ['TRANSPORT_MANAGER'],
    references: [
      { kind: 'TARGET', value: 90, label: 'SLA target' },
      { kind: 'TREND', value: 61.4, label: '4-week average' },
    ],
    evidenceSql: 'SELECT 1',
    ...overrides,
  }
}

describe('KpiCard', () => {
  it('shows "not active yet" when the metric has no overall finding', () => {
    render(<KpiCard title="Cost per km" finding={undefined} />)

    expect(screen.getByText('Cost per km')).toBeInTheDocument()
    expect(screen.getByText('Not active yet')).toBeInTheDocument()
  })

  it('shows observed, trend delta, peer reference, and the tier word', () => {
    const finding = makeFinding({
      references: [
        { kind: 'PEER', value: 64.1, label: 'peer median' },
        { kind: 'TREND', value: 61.4, label: '4-week average' },
      ],
    })
    render(<KpiCard title="On-time arrival" finding={finding} />)

    expect(screen.getByText('59.1%')).toBeInTheDocument()
    expect(screen.getByText(/4-week average/)).toBeInTheDocument()
    expect(screen.getByText(/peer median 64\.1%/)).toBeInTheDocument()
    expect(screen.getByText('Breach')).toBeInTheDocument()
  })

  it('shows a TARGET reference generically, same as PEER (e.g. marshal_compliance vs a hard target)', () => {
    const finding = makeFinding({
      metricId: 'marshal_compliance',
      metricLabel: 'Marshal compliance (dark hours)',
      tier: 'BREACH',
      observed: 93.6,
      references: [{ kind: 'TARGET', value: 100, label: 'SLA target' }],
    })
    render(<KpiCard title="Marshal compliance" finding={finding} />)

    expect(screen.getByText(/SLA target 100%/)).toBeInTheDocument()
    expect(screen.getByText('Breach')).toBeInTheDocument()
  })

  it('colours a rise green for a higher-is-better metric (ota)', () => {
    const finding = makeFinding({
      metricId: 'ota',
      observed: 92,
      references: [{ kind: 'TREND', value: 88, label: '4-week average' }],
    })
    render(<KpiCard title="On-time arrival" finding={finding} />)

    const delta = screen.getByText(/vs 4-week average/)
    expect(delta.className).toContain('kpi-card__delta--good')
    expect(delta).toHaveTextContent('↑')
  })

  it('inverts the colour for a lower-is-better metric (no_show_rate): a rise reads bad', () => {
    const finding = makeFinding({
      metricId: 'no_show_rate',
      metricLabel: 'No-show rate',
      observed: 12,
      references: [{ kind: 'TREND', value: 8, label: '4-week average' }],
    })
    render(<KpiCard title="No-show rate" finding={finding} />)

    const delta = screen.getByText(/vs 4-week average/)
    expect(delta.className).toContain('kpi-card__delta--bad')
    // Same arithmetic direction (a rise) as the ota case, opposite colour.
    expect(delta).toHaveTextContent('↑')
  })

  it('inverts the colour for a lower-is-better metric: a fall reads good', () => {
    const finding = makeFinding({
      metricId: 'no_show_rate',
      metricLabel: 'No-show rate',
      observed: 6,
      references: [{ kind: 'TREND', value: 8, label: '4-week average' }],
    })
    render(<KpiCard title="No-show rate" finding={finding} />)

    const delta = screen.getByText(/vs 4-week average/)
    expect(delta.className).toContain('kpi-card__delta--good')
    expect(delta).toHaveTextContent('↓')
  })
})
