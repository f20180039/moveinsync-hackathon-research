import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import fixture from '../../../handoff/fake-findings.json'
import type { Finding } from '../api/types.ts'
import { FindingsList } from './FindingsList.tsx'

const findings = fixture.findings as Finding[]

describe('FindingsList', () => {
  it('renders findings in the order the server ranked them', () => {
    render(<FindingsList findings={findings} />)

    const metrics = screen.getAllByText(
      (_, element) => element?.tagName.toLowerCase() === 'span' && element.classList.contains('finding-row__metric'),
    )
    const renderedOrder = metrics.map((el) => el.textContent)
    const expectedOrder = findings.map((f) => f.metricLabel)

    expect(renderedOrder).toEqual(expectedOrder)
  })

  it('says so plainly when a sweep found nothing', () => {
    render(<FindingsList findings={[]} />)

    expect(
      screen.getByText('The sweep found nothing above PASS for this window.'),
    ).toBeInTheDocument()
  })

  it('renders a column header naming what each column contains', () => {
    render(<FindingsList findings={findings} />)

    const header = screen.getByRole('row', { name: /severity/i })
    expect(header).toHaveTextContent('Severity')
    expect(header).toHaveTextContent('Metric')
    expect(header).toHaveTextContent('Slice')
    expect(header).toHaveTextContent('Observed')
    expect(header).toHaveTextContent('Compared against')
    expect(header).toHaveTextContent('Confidence')
  })

  it('has the same number of cells in the header as in every row', () => {
    const { container } = render(<FindingsList findings={findings} />)

    const header = screen.getByRole('row', { name: /severity/i })
    const headerCells = within(header).getAllByRole('columnheader')

    const rowToggles = container.querySelectorAll('.finding-row__toggle')
    expect(rowToggles.length).toBe(findings.length)
    for (const toggle of rowToggles) {
      expect(toggle.children.length).toBe(headerCells.length)
    }
  })

  it('header and every row toggle share one grid-alignment class -- same box-sizing/padding/border/gap/grid-template-columns, all sourced from a single rule', () => {
    const { container } = render(<FindingsList findings={findings} />)

    const header = container.querySelector('.findings-header') as HTMLElement
    const rowToggles = container.querySelectorAll('.finding-row__toggle')
    expect(rowToggles.length).toBeGreaterThan(0)

    // jsdom does not apply our stylesheet, so a real computed-style
    // comparison isn't meaningful here (see the shell-scroll structural
    // test above for the same caveat) -- what this test can, and does,
    // guarantee is that the header and every row toggle carry the exact
    // same class, so they read from the exact same CSS rule
    // (.findings-grid-row) for box-sizing, padding, border, gap and
    // grid-template-columns. They cannot drift apart again without this
    // test catching the class being dropped from one side.
    expect(header.classList.contains('findings-grid-row')).toBe(true)
    for (const toggle of rowToggles) {
      expect(toggle.classList.contains('findings-grid-row')).toBe(true)
    }
  })

  it('keeps the cell count in sync after expanding a row, with the evidence panel outside the row grid', async () => {
    const user = userEvent.setup()
    const { container } = render(<FindingsList findings={findings} />)

    const header = screen.getByRole('row', { name: /severity/i })
    const headerCells = within(header).getAllByRole('columnheader')

    const firstToggle = container.querySelector('.finding-row__toggle') as HTMLElement
    await user.click(firstToggle)

    // Expanding a row must not add or remove any of its own grid cells --
    // the same 7 columns line up under the header before and after.
    expect(firstToggle.children.length).toBe(headerCells.length)

    // The evidence panel is a sibling of the toggle button, not one of its
    // grid children -- it renders as its own full-width block below the
    // row, so it never shifts or is counted as part of the row's column
    // template.
    const evidenceRegion = screen.getByRole('region')
    expect(Array.from(firstToggle.children)).not.toContain(evidenceRegion)
    expect(evidenceRegion.parentElement).toBe(firstToggle.parentElement)
    expect(firstToggle.nextElementSibling).toBe(evidenceRegion)
  })
})

// A column that is blank for most rows must say why in the header itself:
// the blank IS the disclosure rule (>= 0.90 discloses nothing), and
// without the rule on screen an empty column reads as missing data.
describe('FindingsList confidence column', () => {
  it('states the disclosure threshold in the header, not only in a tooltip', () => {
    render(<FindingsList findings={findings} />)

    expect(screen.getByText(/Confidence \(if <0\.90\)/)).toBeInTheDocument()
  })
})
