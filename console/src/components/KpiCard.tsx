import { computeDelta, findReference } from '../api/insights.ts'
import { formatMetricValue } from '../api/types.ts'
import type { Finding } from '../api/types.ts'
import { Card } from './Card.tsx'
import { TierBadge } from './TierBadge.tsx'

export interface KpiCardProps {
  title: string
  finding: Finding | undefined
}

// Answers "is this number good or bad?" at a glance: the observed value,
// its own recent history (the trend reference), its peers (the peer
// reference, when the finding carries one), and the tier word -- per the
// jury insight this card exists to demonstrate.
export function KpiCard({ title, finding }: KpiCardProps) {
  if (!finding) {
    return (
      <Card className="kpi-card">
        <h2 className="kpi-card__title">{title}</h2>
        <p className="kpi-card__inactive">Not active yet</p>
      </Card>
    )
  }

  const trendRef = findReference(finding, 'TREND')
  const peerRef = findReference(finding, 'PEER')
  const delta = trendRef ? computeDelta(finding.observed, trendRef.value, finding.metricId, finding.unit) : null

  // Comparison bar: observed vs trend vs peer, each a marker on one track,
  // positioned by relative value (not a sparkline -- there's no honest
  // 5-point history to draw one from).
  const values = [finding.observed, trendRef?.value, peerRef?.value].filter(
    (v): v is number => typeof v === 'number',
  )
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || 1
  const percentFor = (v: number) => ((v - min) / span) * 100

  return (
    <Card className="kpi-card">
      <h2 className="kpi-card__title">{title}</h2>
      <p className="kpi-card__value num">{formatMetricValue(finding.observed, finding.unit)}</p>

      {delta && (
        <p className={`kpi-card__delta ${delta.improved ? 'kpi-card__delta--good' : 'kpi-card__delta--bad'}`}>
          {delta.arrow} {delta.magnitude} {delta.unitWord} vs {trendRef!.label}
        </p>
      )}

      {peerRef && (
        <p className="kpi-card__peer">
          {peerRef.label} {formatMetricValue(peerRef.value, finding.unit)}
        </p>
      )}

      <TierBadge tier={finding.tier} />

      <div
        className="kpi-card__bar"
        role="img"
        aria-label={`Observed ${formatMetricValue(finding.observed, finding.unit)}${
          trendRef ? `, trend ${formatMetricValue(trendRef.value, finding.unit)}` : ''
        }${peerRef ? `, peer ${formatMetricValue(peerRef.value, finding.unit)}` : ''}`}
      >
        <div className="kpi-card__bar-track">
          <span
            className="kpi-card__bar-marker kpi-card__bar-marker--observed"
            style={{ left: `${percentFor(finding.observed)}%` }}
          />
          {trendRef && (
            <span
              className="kpi-card__bar-marker kpi-card__bar-marker--trend"
              style={{ left: `${percentFor(trendRef.value)}%` }}
            />
          )}
          {peerRef && (
            <span
              className="kpi-card__bar-marker kpi-card__bar-marker--peer"
              style={{ left: `${percentFor(peerRef.value)}%` }}
            />
          )}
        </div>
        <div className="kpi-card__bar-legend">
          <span>Observed</span>
          {trendRef && <span>Trend</span>}
          {peerRef && <span>Peer</span>}
        </div>
      </div>
    </Card>
  )
}
