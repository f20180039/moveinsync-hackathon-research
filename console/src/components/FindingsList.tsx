import type { Finding } from '../api/types.ts'
import { FindingRow } from './FindingRow.tsx'

// One definition per column, reused for both the header text and its
// tooltip -- "Also add a one-line title/tooltip on each column header
// repeating its definition." Observed and Confidence are numeric columns,
// right-aligned to match the values beneath them.
const COLUMNS: { label: string; title: string; align?: 'right' }[] = [
  { label: '', title: 'Expand a row to see its evidence' },
  { label: 'Severity', title: 'Pass, Watch, Concern or Breach -- how urgent this is' },
  { label: 'Metric', title: 'Which measured metric this finding is about' },
  { label: 'Slice', title: 'Which vendor, site, tenant, or the overall scope this applies to' },
  { label: 'Observed', title: 'The measured value for this window', align: 'right' },
  {
    label: 'Compared against',
    title: 'The reference values used to judge it -- trend, peer, or target',
  },
  {
    // The rule is IN the header, not only in its tooltip: this cell is
    // deliberately empty for every finding at or above 0.90 (most of
    // them), and a column of blanks under a bare "Confidence" reads as
    // broken data rather than as the disclosure rule working. A tooltip
    // cannot carry that -- nobody hovers a header on a projector.
    label: 'Confidence (if <0.90)',
    title: 'Shown only below 0.9 -- part of the underlying feed was quarantined or unmatched',
    align: 'right',
  },
]

// Renders the findings array exactly as the server ranked it. The backend
// enforces the ordering (a BREACH outranks any number of WATCHes; it is
// deliberately not a weighted score), so this never re-sorts.
export function FindingsList({ findings }: { findings: Finding[] }) {
  if (findings.length === 0) {
    return <p className="findings-list__empty">The sweep found nothing above PASS for this window.</p>
  }

  return (
    <div className="findings" role="table" aria-label="Findings, ranked worst first">
      <div className="findings-header findings-grid-row" role="row">
        {COLUMNS.map((column) => (
          <span
            key={column.label || 'chevron'}
            role="columnheader"
            title={column.title}
            className={column.align === 'right' ? 'num' : undefined}
          >
            {column.label}
          </span>
        ))}
      </div>
      <ul className="findings-list" role="rowgroup">
        {findings.map((finding) => (
          <FindingRow key={finding.id} finding={finding} />
        ))}
      </ul>
    </div>
  )
}
