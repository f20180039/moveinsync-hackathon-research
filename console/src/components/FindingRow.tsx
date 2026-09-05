import { useId, useState } from 'react'
import { formatSliceLabel } from '../api/labels.ts'
import type { Finding } from '../api/types.ts'
import {
  NOT_MEASURED,
  NOT_MEASURED_EXPLANATION,
  formatMetricValue,
  isDataGap,
  shouldDiscloseConfidence,
} from '../api/types.ts'
import { EvidencePanel } from './EvidencePanel.tsx'
import { TierBadge } from './TierBadge.tsx'

export function FindingRow({ finding }: { finding: Finding }) {
  const [expanded, setExpanded] = useState(false)
  const panelId = useId()

  return (
    // role="row" on the <li> gives the ranked list table-like structure for
    // assistive tech, matching the column header row in FindingsList. The
    // toggle stays a plain, unambiguous <button> (its own implicit role is
    // untouched) so it's still reachable as a button by keyboard and by
    // existing getByRole('button', ...) queries -- a real ARIA grid would
    // also mark each cell, but that would require nesting cell roles inside
    // an interactive control, which browsers don't expose reliably. This is
    // the pragmatic middle: row-level structure, unbroken button semantics.
    <li className="finding-row" role="row">
      <button
        type="button"
        className="btn finding-row__toggle"
        aria-expanded={expanded}
        aria-controls={panelId}
        onClick={() => setExpanded((value) => !value)}
      >
        <span className="finding-row__chevron" aria-hidden="true">
          {expanded ? '▾' : '▸'}
        </span>
        <TierBadge tier={finding.tier} />
        <span className="finding-row__metric">{finding.metricLabel}</span>
        <span className="finding-row__slice">{formatSliceLabel(finding.sliceLabel)}</span>
        <span className="finding-row__observed num">
          {isDataGap(finding) ? NOT_MEASURED : formatMetricValue(finding.observed, finding.unit)}
        </span>
        <span className="finding-row__references">
          {isDataGap(finding) ? (
            <span className="finding-row__reference">{NOT_MEASURED_EXPLANATION}</span>
          ) : (
            finding.references.map((ref) => (
              <span key={`${ref.kind}-${ref.label}`} className="finding-row__reference">
                {ref.label} {formatMetricValue(ref.value, finding.unit)}
              </span>
            ))
          )}
        </span>
        {/* Always rendered (even empty) so every row has the same number of
            cells as the header, regardless of whether this finding's
            confidence clears the disclosure threshold. */}
        <span className="finding-row__confidence num">
          {shouldDiscloseConfidence(finding.confidence) ? `confidence ${finding.confidence.toFixed(2)}` : null}
        </span>
      </button>
      {expanded && (
        <div id={panelId} role="region" aria-label={`Evidence for ${finding.metricLabel}`}>
          <EvidencePanel finding={finding} />
        </div>
      )}
    </li>
  )
}
