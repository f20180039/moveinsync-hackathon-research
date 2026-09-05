import { barDomain, barPercent, computeDelta, findReference } from '../api/insights.ts'
import { label } from '../api/labels.ts'
import { formatMetricValue } from '../api/types.ts'
import type { Finding, Reference } from '../api/types.ts'
import { Card } from './Card.tsx'
import { TierBadge } from './TierBadge.tsx'

export interface KpiCardProps {
  title: string
  finding: Finding | undefined
}

// Answers "is this number good or bad?" at a glance: the observed value,
// its own recent history (the TREND reference, as a delta), and every
// other reference it carries (PEER, TARGET, or a kind that doesn't exist
// yet) rendered generically -- plus the tier word. Per the jury insight
// this card exists to demonstrate: is 92% good or bad, compared to whom.
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
  // Every reference besides TREND, shown generically -- PEER ("peer
  // median 64.1%"), TARGET ("SLA target 90%"), or a kind introduced later.
  // No switch on `kind` here, matching the rest of the console.
  const otherRefs: Reference[] = finding.references.filter((ref) => ref.kind !== 'TREND')
  const delta = trendRef ? computeDelta(finding.observed, trendRef.value, finding.metricId, finding.unit) : null

  // Comparison bar: observed vs every reference, each a marker on one
  // track (not a sparkline -- there's no honest 5-point history to draw
  // one from). The SCALE is barDomain's, not the values' own min and max:
  // normalising to the data itself pinned the lowest value hard left and
  // the highest hard right every time, so a 0.2-point gap and a 40-point
  // gap drew an identical picture -- two dots at the ends of a line, which
  // is exactly what it looked like. The axis is now stated, and labelled
  // at both ends, so the distance between markers means something.
  const values = [finding.observed, ...finding.references.map((ref) => ref.value)]
  const domain = barDomain(values, finding.unit)
  const percentFor = (v: number) => barPercent(v, domain)

  const barLabelParts = [
    `Observed ${formatMetricValue(finding.observed, finding.unit)}`,
    ...finding.references.map((ref) => `${ref.label || label('referenceKind', ref.kind)} ${formatMetricValue(ref.value, finding.unit)}`),
  ]

  return (
    <Card className="kpi-card">
      <h2 className="kpi-card__title">{title}</h2>
      <p className="kpi-card__value num">{formatMetricValue(finding.observed, finding.unit)}</p>

      {delta && (
        <p className={`kpi-card__delta ${delta.improved ? 'kpi-card__delta--good' : 'kpi-card__delta--bad'}`}>
          {delta.arrow} {delta.magnitude} {delta.unitWord} vs {trendRef!.label}
        </p>
      )}

      {otherRefs.map((ref) => (
        <p key={ref.kind} className="kpi-card__reference">
          {ref.label || label('referenceKind', ref.kind)} {formatMetricValue(ref.value, finding.unit)}
        </p>
      ))}

      <TierBadge tier={finding.tier} />

      <div className="kpi-card__bar" role="img" aria-label={barLabelParts.join(', ')}>
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
          {otherRefs.map((ref) => (
            <span
              key={ref.kind}
              className="kpi-card__bar-marker kpi-card__bar-marker--peer"
              style={{ left: `${percentFor(ref.value)}%` }}
            />
          ))}
        </div>
        <div className="kpi-card__bar-axis" aria-hidden="true">
          <span>{formatMetricValue(domain.min, finding.unit)}</span>
          <span>{formatMetricValue(domain.max, finding.unit)}</span>
        </div>
        {/* Each legend entry carries the dot's own colour, so a reader can
            tell which marker is which -- an unkeyed list of words could
            not. */}
        <div className="kpi-card__bar-legend">
          <span className="kpi-card__bar-key">
            <span className="kpi-card__bar-swatch kpi-card__bar-marker--observed" />
            Observed
          </span>
          {trendRef && (
            <span className="kpi-card__bar-key">
              <span className="kpi-card__bar-swatch kpi-card__bar-marker--trend" />
              Trend
            </span>
          )}
          {otherRefs.map((ref) => (
            <span key={ref.kind} className="kpi-card__bar-key">
              <span className="kpi-card__bar-swatch kpi-card__bar-marker--peer" />
              {ref.label || label('referenceKind', ref.kind)}
            </span>
          ))}
        </div>
      </div>
    </Card>
  )
}
