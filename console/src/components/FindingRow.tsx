import { useId, useState } from 'react'
import type { Finding } from '../api/types.ts'
import { formatMetricValue, shouldDiscloseConfidence } from '../api/types.ts'
import { EvidencePanel } from './EvidencePanel.tsx'
import { TierBadge } from './TierBadge.tsx'

export function FindingRow({ finding }: { finding: Finding }) {
  const [expanded, setExpanded] = useState(false)
  const panelId = useId()

  return (
    <li className="finding-row">
      <button
        type="button"
        className="finding-row__toggle"
        aria-expanded={expanded}
        aria-controls={panelId}
        onClick={() => setExpanded((value) => !value)}
      >
        <TierBadge tier={finding.tier} />
        <span className="finding-row__metric">{finding.metricLabel}</span>
        <span className="finding-row__slice">{finding.sliceLabel}</span>
        <span className="finding-row__observed">{formatMetricValue(finding.observed, finding.unit)}</span>
        <span className="finding-row__references">
          {finding.references.map((ref) => (
            <span key={`${ref.kind}-${ref.label}`} className="finding-row__reference">
              {ref.label} {formatMetricValue(ref.value, finding.unit)}
            </span>
          ))}
        </span>
        {shouldDiscloseConfidence(finding.confidence) && (
          <span className="finding-row__confidence">
            confidence {finding.confidence.toFixed(2)}
          </span>
        )}
      </button>
      {expanded && (
        <div id={panelId} role="region" aria-label={`Evidence for ${finding.metricLabel}`}>
          <EvidencePanel finding={finding} />
        </div>
      )}
    </li>
  )
}
