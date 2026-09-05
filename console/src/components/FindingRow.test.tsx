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

  it('shows the Recurring tag in the Severity cell once recurrence clears the threshold, without adding a grid cell', () => {
    // Task 16's `recurrence` field isn't in the shared fixture yet --
    // extended locally here on one BREACH row.
    const recurringFinding: Finding = {
      ...twoReferenceHighConfidence,
      recurrence: { weeks: 3, of: 4 },
    }
    const { container } = render(<FindingRow finding={recurringFinding} />)

    expect(screen.getByText(/3 of the last 4 weeks/)).toBeInTheDocument()

    const toggle = container.querySelector('.finding-row__toggle') as HTMLElement
    expect(toggle.children.length).toBe(7)
  })

  it('never shows a bare 0 for a DATA_GAP finding -- an em dash and an explanation instead', async () => {
    const dataGapFinding: Finding = {
      ...twoReferenceHighConfidence,
      id: 'synthetic-data-gap',
      cause: 'DATA_GAP',
      observed: 0.0,
      references: [],
    }
    const user = userEvent.setup()
    render(<FindingRow finding={dataGapFinding} />)

    // The collapsed row: an em dash, not "0%".
    expect(screen.queryByText('0%')).not.toBeInTheDocument()
    expect(screen.getByText('—')).toBeInTheDocument()
    expect(screen.getByText('could not be measured')).toBeInTheDocument()

    // The expanded panel: same treatment for Observed and Compared against.
    await user.click(screen.getByRole('button'))
    const panel = screen.getByRole('region')
    expect(within(panel).getByText('—')).toBeInTheDocument()
    expect(within(panel).getByText('could not be measured')).toBeInTheDocument()
  })
})
