import type { Finding } from '../api/types.ts'
import { causePhrase, formatMetricValue } from '../api/types.ts'
import { Button } from './Button.tsx'

// Expanded region for one finding: observed value, every reference, the rule
// that fired, confidence, audiences, and the SQL that produced the number.
// This panel is the answer to "where did this come from" -- the SQL is the
// point of it, so it is never truncated.
export function EvidencePanel({ finding }: { finding: Finding }) {
  function copySql() {
    // navigator.clipboard is not present in jsdom / some embedded browsers --
    // guard so a click never throws in tests or in a locked-down runtime.
    if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(finding.evidenceSql).catch(() => {})
    }
  }

  return (
    <div className="evidence-panel">
      <dl className="evidence-panel__facts">
        <dt>Observed</dt>
        <dd>{formatMetricValue(finding.observed, finding.unit)}</dd>

        {finding.references.map((ref) => (
          <div key={`${ref.kind}-${ref.label}`} className="evidence-panel__ref">
            <dt>{ref.label}</dt>
            <dd>{formatMetricValue(ref.value, finding.unit)}</dd>
          </div>
        ))}

        <dt>Rule that fired</dt>
        <dd>{causePhrase(finding.cause)}</dd>

        <dt>Confidence</dt>
        <dd>{finding.confidence.toFixed(2)}</dd>

        <dt>Sent to</dt>
        <dd>{finding.audiences.join(', ')}</dd>
      </dl>

      <div className="evidence-panel__sql">
        <div className="evidence-panel__sql-header">
          <span>Evidence SQL</span>
          <Button variant="ghost" size="sm" onClick={copySql}>
            Copy SQL
          </Button>
        </div>
        <pre className="evidence-panel__sql-block">{finding.evidenceSql}</pre>
      </div>
    </div>
  )
}
