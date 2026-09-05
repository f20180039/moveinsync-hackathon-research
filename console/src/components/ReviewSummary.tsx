import { isRecurring } from '../api/insights.ts'
import { formatSliceLabel, label } from '../api/labels.ts'
import type { Finding, Tier } from '../api/types.ts'
import {
  NOT_MEASURED,
  NOT_MEASURED_EXPLANATION,
  TIER_ORDER,
  formatMetricValue,
  isAlertTier,
  isDataGap,
} from '../api/types.ts'

// Worst first -- a review is read top-down for what went wrong, so Breach
// leads the bar and the legend. TIER_ORDER itself is best-to-worst and is
// shared with the rest of the console; reversing here rather than adding a
// second constant keeps one definition of the scale.
const TIERS_WORST_FIRST: readonly Tier[] = [...TIER_ORDER].reverse()

const WORST_SLICE_LIMIT = 8
const RECURRING_LIMIT = 10
const METRICS_PER_SLICE_SHOWN = 3

interface TierSlice {
  tier: Tier
  count: number
  share: number
  offset: number
}

// Counts of the findings actually in the payload, and each count's share of
// that same payload. Nothing here is modelled, extrapolated or filled in:
// a tier with no findings is omitted entirely rather than rendered as a
// zero, which is the same rule the rest of the console follows for a
// metric with no computable reference.
export function tierMix(findings: Finding[]): TierSlice[] {
  const total = findings.length
  if (total === 0) return []
  const slices: TierSlice[] = []
  let offset = 0
  for (const tier of TIERS_WORST_FIRST) {
    const count = findings.filter((f) => f.tier === tier).length
    if (count === 0) continue
    const share = (count / total) * 100
    slices.push({ tier, count, share, offset })
    offset += share
  }
  return slices
}

export interface MetricRow {
  metricId: string
  metricLabel: string
  unit: string
  total: number
  needsAttention: number
  // The worst *measured* finding for this metric: largest gap among the
  // Concern/Breach ones, skipping DATA_GAP findings whose 0.0 is the
  // absence of a measurement rather than a measurement of zero. null when
  // the metric has nothing above Watch -- the row then says so instead of
  // nominating a "worst" that isn't one.
  worst: Finding | null
}

export function metricRows(findings: Finding[]): MetricRow[] {
  const byMetric = new Map<string, Finding[]>()
  for (const finding of findings) {
    const bucket = byMetric.get(finding.metricId)
    if (bucket) bucket.push(finding)
    else byMetric.set(finding.metricId, [finding])
  }

  const rows: MetricRow[] = []
  for (const [metricId, group] of byMetric) {
    const alerting = group.filter((f) => isAlertTier(f.tier) && !isDataGap(f))
    const worst = alerting.reduce<Finding | null>(
      (best, f) => (best === null || Math.abs(f.gap) > Math.abs(best.gap) ? f : best),
      null,
    )
    rows.push({
      metricId,
      metricLabel: group[0].metricLabel,
      unit: group[0].unit,
      total: group.length,
      needsAttention: group.filter((f) => isAlertTier(f.tier)).length,
      worst,
    })
  }

  return rows.sort((a, b) => b.needsAttention - a.needsAttention || b.total - a.total)
}

export interface SliceRow {
  sliceLabel: string
  breach: number
  concern: number
  metricLabels: string[]
}

// Slices ranked by how much of the window's attention they own. Ranked on
// counts, never on summed gaps: gap is in the metric's own unit (%, INR,
// INR/km) and adding those together would be an invented number.
export function worstSlices(findings: Finding[]): SliceRow[] {
  const alerting = findings.filter((f) => isAlertTier(f.tier))
  const bySlice = new Map<string, SliceRow>()
  for (const finding of alerting) {
    let row = bySlice.get(finding.sliceLabel)
    if (!row) {
      row = { sliceLabel: finding.sliceLabel, breach: 0, concern: 0, metricLabels: [] }
      bySlice.set(finding.sliceLabel, row)
    }
    if (finding.tier === 'BREACH') row.breach += 1
    else row.concern += 1
    if (!row.metricLabels.includes(finding.metricLabel)) row.metricLabels.push(finding.metricLabel)
  }
  return [...bySlice.values()].sort(
    (a, b) => b.breach - a.breach || b.concern - a.concern || a.sliceLabel.localeCompare(b.sliceLabel),
  )
}

function referenceText(finding: Finding): string {
  const ref = finding.references[0]
  if (!ref) return NOT_MEASURED_EXPLANATION
  return `${ref.label || label('referenceKind', ref.kind)} ${formatMetricValue(ref.value, finding.unit)}`
}

function observedText(finding: Finding): string {
  return isDataGap(finding) ? NOT_MEASURED : formatMetricValue(finding.observed, finding.unit)
}

// The review's visual summary: what the window's verdicts look like, which
// metrics carry them, which slices own them, and which of them are not new.
// Every number is a count of, or a value read straight off, the findings
// payload it was handed -- there is no second data source and nothing is
// derived beyond counting and each count's share of the same total. A
// section with nothing to say renders nothing at all rather than a table of
// zeroes.
export function ReviewSummary({ findings }: { findings: Finding[] }) {
  if (findings.length === 0) {
    return <p className="review-summary__empty">This run produced no findings, so there is nothing to review.</p>
  }

  const mix = tierMix(findings)
  const metrics = metricRows(findings)
  const slices = worstSlices(findings)
  const recurring = findings.filter(isRecurring)
  const needsAttention = findings.filter((f) => isAlertTier(f.tier)).length

  return (
    <div className="review-summary">
      <section>
        <h2 className="panel-heading">Verdict mix</h2>
        <p className="review-summary__lede">
          {findings.length} findings in this window · {needsAttention} need attention
        </p>
        {/* Inline SVG on purpose -- no charting library in this repo, and
            no network at demo time. preserveAspectRatio="none" lets the
            100-unit viewBox stretch to whatever width the page gives it,
            so the segment widths stay exact shares. */}
        <svg
          className="review-summary__bar"
          viewBox="0 0 100 10"
          preserveAspectRatio="none"
          role="img"
          aria-label={mix.map((s) => `${label('tier', s.tier)} ${s.count}`).join(', ')}
        >
          {mix.map((s) => (
            <rect
              key={s.tier}
              className={`review-summary__seg review-summary__seg--${s.tier.toLowerCase()}`}
              x={s.offset}
              y={0}
              width={s.share}
              height={10}
            />
          ))}
        </svg>
        <ul className="review-summary__legend">
          {mix.map((s) => (
            <li key={s.tier}>
              <span className={`review-summary__swatch review-summary__swatch--${s.tier.toLowerCase()}`} aria-hidden="true" />
              {label('tier', s.tier)} <strong className="num">{s.count}</strong>{' '}
              <span className="review-summary__share num">{s.share.toFixed(0)}%</span>
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h2 className="panel-heading">By metric</h2>
        <table className="review-table">
          <thead>
            <tr>
              <th>Metric</th>
              <th className="num">Findings</th>
              <th className="num">Needs attention</th>
              <th>Worst slice</th>
              <th className="num">Observed</th>
              <th>Compared against</th>
            </tr>
          </thead>
          <tbody>
            {metrics.map((row) => (
              <tr key={row.metricId}>
                <td>{row.metricLabel}</td>
                <td className="num">{row.total}</td>
                <td className="num">{row.needsAttention}</td>
                {row.worst ? (
                  <>
                    <td>{formatSliceLabel(row.worst.sliceLabel)}</td>
                    <td className="num">{observedText(row.worst)}</td>
                    <td>{referenceText(row.worst)}</td>
                  </>
                ) : (
                  <td colSpan={3} className="review-table__quiet">
                    nothing above Watch this window
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {slices.length > 0 && (
        <section>
          <h2 className="panel-heading">Worst slices</h2>
          <p className="review-summary__lede">
            Ranked by how many Breach and Concern findings each slice owns — gaps are in each metric's own unit and are
            never added together.
          </p>
          <table className="review-table">
            <thead>
              <tr>
                <th>Slice</th>
                <th className="num">{label('tier', 'BREACH')}</th>
                <th className="num">{label('tier', 'CONCERN')}</th>
                <th>Metrics affected</th>
              </tr>
            </thead>
            <tbody>
              {slices.slice(0, WORST_SLICE_LIMIT).map((row) => (
                <tr key={row.sliceLabel}>
                  <td>{formatSliceLabel(row.sliceLabel)}</td>
                  <td className="num">{row.breach > 0 ? row.breach : NOT_MEASURED}</td>
                  <td className="num">{row.concern > 0 ? row.concern : NOT_MEASURED}</td>
                  <td>
                    {row.metricLabels.slice(0, METRICS_PER_SLICE_SHOWN).join(', ')}
                    {row.metricLabels.length > METRICS_PER_SLICE_SHOWN &&
                      ` +${row.metricLabels.length - METRICS_PER_SLICE_SHOWN} more`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {slices.length > WORST_SLICE_LIMIT && (
            <p className="review-summary__more">
              {slices.length - WORST_SLICE_LIMIT} more slices need attention — see Insights for the full list.
            </p>
          )}
        </section>
      )}

      {/* `recurrence` is optional on the wire: a service that does not
          compute it yet leaves this section off entirely rather than
          claiming nothing recurs. */}
      {recurring.length > 0 && (
        <section>
          <h2 className="panel-heading">Recurring — not new this window</h2>
          <table className="review-table">
            <thead>
              <tr>
                <th>Slice</th>
                <th>Metric</th>
                <th>Weeks</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {recurring.slice(0, RECURRING_LIMIT).map((finding) => (
                <tr key={finding.id}>
                  <td>{formatSliceLabel(finding.sliceLabel)}</td>
                  <td>{finding.metricLabel}</td>
                  <td className="num">
                    {finding.recurrence?.weeks} of {finding.recurrence?.of}
                  </td>
                  <td>{finding.action || <span className="review-table__quiet">no action computed</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {recurring.length > RECURRING_LIMIT && (
            <p className="review-summary__more">{recurring.length - RECURRING_LIMIT} more recurring findings.</p>
          )}
        </section>
      )}
    </div>
  )
}
