import { useState } from 'react'
import { decomposeFinding, dispatch } from '../api/client.ts'
import { markDismissed } from '../api/dismissed.ts'
import { buildFindingSentence, sliceForSentence } from '../api/insights.ts'
import { causePhrase, formatContributorName, label, sliceDimensionTag } from '../api/labels.ts'
import type { DecomposeDimension, DecomposeResponse, DispatchAudienceResult, Finding } from '../api/types.ts'
import { formatMetricValue, isDataGap } from '../api/types.ts'
import { Button } from './Button.tsx'
import { Card } from './Card.tsx'
import { EvidencePanel } from './EvidencePanel.tsx'
import { RecurringTag } from './RecurringTag.tsx'
import { TierBadge } from './TierBadge.tsx'

const DECOMPOSE_DIMENSIONS: DecomposeDimension[] = ['VENDOR', 'SITE', 'SHIFT', 'DELAY_REASON']

export interface PriorityActionCardProps {
  finding: Finding
  runId: string
  onDismiss: (findingId: string) => void
}

// "Pooja Sokolov Travel owns 4.1 pts, Vikram Mikhailov Travel 1.3 pts" --
// the verb only needs saying once. Shared between the server-computed
// `finding.owns` (always available, no fetch) and the on-demand
// `/decompose` result (Investigate's dimension selector).
function topContributorsText(rows: { value: string; pointsOfGap: number }[]): string {
  return rows
    .slice(0, 2)
    .map((row, index) => {
      const name = formatContributorName(row.value)
      return index === 0 ? `${name} owns ${row.pointsOfGap.toFixed(1)} pts` : `${name} ${row.pointsOfGap.toFixed(1)} pts`
    })
    .join(', ')
}

// One finding as an actionable card: stripe + tier word (never colour
// alone), the plain-English sentence, three fact columns, and the
// Investigate/Escalate/Dismiss actions. Reused as-is by the Overview
// panel (Stage 2, top 5) and the Alerts page (Stage 3, all of them).
//
// The "Why" column's top-2 contributors come from `finding.owns` --
// computed server-side and already present on the finding, precisely so
// this card never has to fetch anything just to render. `/decompose` is
// fetched only when Investigate is opened (for its dimension selector),
// never on mount: with 5 cards on Overview, a mount-time fetch per card
// was 5 requests for data the card usually already had via `owns`.
export function PriorityActionCard({ finding, runId, onDismiss }: PriorityActionCardProps) {
  const [expanded, setExpanded] = useState(false)
  const [dim, setDim] = useState<DecomposeDimension>('VENDOR')
  const [decompose, setDecompose] = useState<DecomposeResponse | null>(null)
  const [escalating, setEscalating] = useState(false)
  const [escalateError, setEscalateError] = useState<string | null>(null)
  const [escalateResult, setEscalateResult] = useState<DispatchAudienceResult[] | null>(null)

  async function loadDecompose(nextDim: DecomposeDimension) {
    setDim(nextDim)
    const result = await decomposeFinding(finding.id, nextDim)
    setDecompose(result)
  }

  async function toggleInvestigate() {
    const next = !expanded
    setExpanded(next)
    if (next && !decompose) {
      await loadDecompose(dim)
    }
  }

  async function escalate() {
    setEscalating(true)
    setEscalateError(null)
    try {
      const result = await dispatch(runId, ['FACILITIES_HEAD'])
      setEscalateResult(result.dispatched)
    } catch (err) {
      setEscalateError(err instanceof Error ? err.message : String(err))
    } finally {
      setEscalating(false)
    }
  }

  function handleDismiss() {
    markDismissed(finding.id)
    onDismiss(finding.id)
  }

  // Decomposition trips, if the user opened Investigate and fetched one;
  // else the trip count already summed from `finding.owns`, if present.
  const decomposeTrips =
    decompose && Array.isArray(decompose.rows) ? decompose.rows.reduce((sum, row) => sum + row.n, 0) : null
  const ownsTrips =
    finding.owns && finding.owns.length > 0 ? finding.owns.reduce((sum, row) => sum + row.n, 0) : null
  const totalTrips = decomposeTrips ?? ownsTrips

  const whyText =
    finding.owns && finding.owns.length > 0 ? topContributorsText(finding.owns) : causePhrase(finding.cause)

  const bareSlice = sliceForSentence(finding.sliceLabel)
  const dimensionTag = sliceDimensionTag(finding.sliceLabel)

  return (
    <Card className={`priority-card priority-card--${finding.tier.toLowerCase()}`}>
      <div className="priority-card__stripe" aria-hidden="true" />
      <div className="priority-card__body">
        <div className="priority-card__header">
          <h3 className="priority-card__title">
            {finding.metricLabel}
            {bareSlice && (
              <>
                {' — '}
                {bareSlice}
                {dimensionTag && <span className="priority-card__dimension-tag">{dimensionTag}</span>}
              </>
            )}
          </h3>
          <TierBadge tier={finding.tier} />
          <RecurringTag finding={finding} />
        </div>

        <p className="priority-card__sentence">{buildFindingSentence(finding)}</p>

        {/* The action is the whole point of a page called "Priority actions",
            and it is already on the wire (computed server-side, deterministic).
            It reads on the collapsed card, directly under the sentence, so the
            default screen answers "what do I do next" without a click. */}
        {finding.action && <p className="priority-card__action">Action: {finding.action}</p>}

        <div className="priority-card__columns">
          <div className="priority-card__column">
            <h4>Why</h4>
            <p>{whyText}</p>
          </div>
          <div className="priority-card__column">
            <h4>Impact</h4>
            <p className="num">
              {isDataGap(finding) ? '—' : formatMetricValue(Math.abs(finding.gap), finding.unit)}
              {totalTrips !== null && ` · ${totalTrips} trips`}
            </p>
          </div>
          <div className="priority-card__column">
            <h4>Compared against</h4>
            {finding.references.length === 0 ? (
              <p>could not be measured</p>
            ) : (
              finding.references.map((ref) => (
                <p key={ref.kind}>
                  {ref.label || label('referenceKind', ref.kind)} {formatMetricValue(ref.value, finding.unit)}
                </p>
              ))
            )}
          </div>
        </div>

        <div className="priority-card__actions">
          <Button variant="primary" aria-expanded={expanded} onClick={toggleInvestigate}>
            Investigate
          </Button>
          <Button onClick={escalate} busy={escalating}>
            Escalate
          </Button>
          <Button variant="ghost" onClick={handleDismiss}>
            Dismiss
          </Button>
        </div>

        {escalateError && <p className="priority-card__error">{escalateError}</p>}

        {escalateResult && (
          <ul className="priority-card__escalate-results">
            {escalateResult.map((result) => (
              <li key={result.audience}>
                <strong>{label('audience', result.audience)}</strong>
                <ul>
                  {result.channels.map((channel) => (
                    <li key={channel.channel}>
                      {label('channel', channel.channel)} · {channel.delivered ? 'delivered' : channel.detail}
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        )}

        {expanded && (
          <div className="priority-card__investigate">
            <EvidencePanel finding={finding} />
            <div className="priority-card__decompose">
              <div className="priority-card__decompose-dims" role="group" aria-label="Decompose by">
                {DECOMPOSE_DIMENSIONS.map((d) => (
                  <Button
                    key={d}
                    size="sm"
                    variant={d === dim ? 'secondary' : 'ghost'}
                    onClick={() => loadDecompose(d)}
                  >
                    {label('dimension', d)}
                  </Button>
                ))}
              </div>
              {decompose && Array.isArray(decompose.rows) && decompose.rows.length > 0 ? (
                <table className="priority-card__decompose-table">
                  <thead>
                    <tr>
                      <th>{label('dimension', decompose.dim)}</th>
                      <th className="num">Share</th>
                      <th className="num">Points of gap</th>
                      <th className="num">Trips</th>
                    </tr>
                  </thead>
                  <tbody>
                    {decompose.rows.map((row) => (
                      <tr key={row.value}>
                        <td>{row.label}</td>
                        <td className="num">{row.shareOfVolume.toFixed(1)}%</td>
                        <td className="num">{row.pointsOfGap.toFixed(1)}</td>
                        <td className="num">{row.n}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <p className="priority-card__decompose-empty">Decomposition not available yet.</p>
              )}
            </div>
          </div>
        )}
      </div>
    </Card>
  )
}
