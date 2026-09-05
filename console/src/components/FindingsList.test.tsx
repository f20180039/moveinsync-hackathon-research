import { render, screen, within } from '@testing-library/react'
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
})
