import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import fixture from '../../../handoff/fake-findings.json'
import type { Finding } from '../api/types.ts'
import { FindingRow } from './FindingRow.tsx'

const findings = fixture.findings as Finding[]

// "overall" On-time arrival: BREACH, confidence 0.96, two references
// (SLA target + 4-week average).
const twoReferenceHighConfidence = findings.find((f) => f.id === '563931f15cdd')!

// Rider experience: WATCH, confidence 0.86 -- below the 0.9 disclosure line.
const lowConfidenceFinding = findings.find((f) => f.id === '1b2f04ef7780')!

describe('FindingRow', () => {
  it('shows every reference point for a finding that has two', () => {
    render(<FindingRow finding={twoReferenceHighConfidence} />)

    expect(screen.getByText(/SLA target/)).toBeInTheDocument()
    expect(screen.getByText(/90/)).toBeInTheDocument()
    expect(screen.getByText(/4-week average/)).toBeInTheDocument()
    expect(screen.getByText(/61\.4/)).toBeInTheDocument()
  })

  it('discloses confidence only when it is below 0.9 -- hidden case (0.96)', () => {
    render(<FindingRow finding={twoReferenceHighConfidence} />)

    expect(screen.queryByText(/confidence/)).not.toBeInTheDocument()
  })

  it('discloses confidence only when it is below 0.9 -- shown case (0.86)', () => {
    render(<FindingRow finding={lowConfidenceFinding} />)

    expect(screen.getByText('confidence 0.86')).toBeInTheDocument()
  })

  it('hides the evidence until asked, then shows the SQL', async () => {
    const user = userEvent.setup()
    render(<FindingRow finding={twoReferenceHighConfidence} />)

    expect(screen.queryByText(/SELECT/)).not.toBeInTheDocument()

    const toggle = screen.getByRole('button', { expanded: false })
    await user.click(toggle)

    expect(screen.getByText(/SELECT/)).toBeInTheDocument()
    expect(screen.getByRole('button', { expanded: true })).toBeInTheDocument()
  })

  it('names the rule that fired alongside the number, once expanded', async () => {
    const user = userEvent.setup()
    render(<FindingRow finding={twoReferenceHighConfidence} />)

    await user.click(screen.getByRole('button'))

    const panel = screen.getByRole('region')
    expect(screen.getAllByText(/59\.1/).length).toBeGreaterThan(0)
    expect(within(panel).getByText(/below its SLA target/)).toBeInTheDocument()
  })
})
