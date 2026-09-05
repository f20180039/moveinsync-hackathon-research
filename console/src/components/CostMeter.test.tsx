import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import fixture from '../../../handoff/fake-findings.json'
import type { Cost } from '../api/types.ts'
import { CostMeter } from './CostMeter.tsx'

const configuredCost = fixture.cost as Cost

describe('CostMeter', () => {
  it('shows figures when pricing is configured and calls exist', () => {
    render(<CostMeter cost={configuredCost} />)

    expect(screen.getByText('3')).toBeInTheDocument() // calls
    expect(screen.queryByText(/pricing not configured/)).not.toBeInTheDocument()
  })

  it('shows the unconfigured state without inventing a rupee figure when pricing is not configured', () => {
    const unconfigured: Cost = { ...configuredCost, pricingConfigured: false }
    render(<CostMeter cost={unconfigured} />)

    expect(screen.getByText('pricing not configured / no calls yet')).toBeInTheDocument()
    expect(screen.queryByText(/₹/)).not.toBeInTheDocument()
  })

  it('shows the unconfigured state without inventing a rupee figure when there have been no calls', () => {
    const noCalls: Cost = { ...configuredCost, calls: 0 }
    render(<CostMeter cost={noCalls} />)

    expect(screen.getByText('pricing not configured / no calls yet')).toBeInTheDocument()
    expect(screen.queryByText(/₹/)).not.toBeInTheDocument()
  })
})
