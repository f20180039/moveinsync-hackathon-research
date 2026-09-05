import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { Finding } from '../api/types.ts'
import { KpiRow } from './KpiRow.tsx'

function makeFinding(overrides: Partial<Finding>): Finding {
  return {
    id: 'f1',
    metricId: 'ota',
    metricLabel: 'On-time arrival',
    unit: '%',
    sliceLabel: 'overall',
    tier: 'WATCH',
    cause: 'BELOW_TARGET',
    observed: 92,
    gap: 3,
    confidence: 0.96,
    audiences: ['TRANSPORT_MANAGER'],
    references: [],
    evidenceSql: 'SELECT 1',
    ...overrides,
  }
}

describe('KpiRow', () => {
  it('defaults to Transport manager\'s four metrics', () => {
    render(<KpiRow findings={[]} />)

    expect(screen.getByText('On-time arrival')).toBeInTheDocument()
    expect(screen.getByText('On-time departure')).toBeInTheDocument()
    expect(screen.getByText('No-show rate')).toBeInTheDocument()
    expect(screen.getByText('Cost per km')).toBeInTheDocument()
  })

  it('renders whatever metric ids it is given, titled via label(\'metric\', ...)', () => {
    render(
      <KpiRow
        findings={[makeFinding({ metricId: 'marshal_compliance', metricLabel: 'Marshal compliance' })]}
        metricIds={['ota', 'cost_per_km', 'cost_per_rider', 'marshal_compliance']}
      />,
    )

    expect(screen.getByText('On-time arrival')).toBeInTheDocument()
    expect(screen.getByText('Cost per km')).toBeInTheDocument()
    // cost_per_rider has no METRIC_LABELS entry -- humanise() fallback.
    expect(screen.getByText('Cost per rider')).toBeInTheDocument()
    expect(screen.getByText('Marshal compliance (dark hours)')).toBeInTheDocument()
  })

  it('shows "Not active yet" for a metric id with no overall finding (e.g. cost_per_rider, not always active)', () => {
    render(<KpiRow findings={[]} metricIds={['cost_per_rider']} />)

    expect(screen.getByText('Cost per rider')).toBeInTheDocument()
    expect(screen.getByText('Not active yet')).toBeInTheDocument()
  })
})
