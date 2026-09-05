import { useEffect, useState } from 'react'
import { decomposeFinding, dispatch } from '../api/client.ts'
import { markDismissed } from '../api/dismissed.ts'
import { buildFindingSentence } from '../api/insights.ts'
import { causePhrase, formatSliceLabel, label } from '../api/labels.ts'
import type { DecomposeDimension, DecomposeResponse, DispatchAudienceResult, Finding } from '../api/types.ts'
import { formatMetricValue, isDataGap } from '../api/types.ts'
import { Button } from './Button.tsx'
import { Card } from './Card.tsx'
import { EvidencePanel } from './EvidencePanel.tsx'
import { TierBadge } from './TierBadge.tsx'

const DECOMPOSE_DIMENSIONS: DecomposeDimension[] = ['VENDOR', 'SITE', 'SHIFT', 'DELAY_REASON']

export interface PriorityActionCardProps {
  finding: Finding
  runId: string
  onDismiss: (findingId: string) => void
}

// One finding as an actionable card: stripe + tier word (never colour
// alone), the plain-English sentence, three fact columns, and the
// Investigate/Escalate/Dismiss actions. Reused as-is by the Overview
// panel (Stage 2, top 5) and the Alerts page (Stage 3, all of them).
export function PriorityActionCard({ finding, runId, onDismiss }: PriorityActionCardProps) {
  const [expanded, setExpanded] = useState(false)
  const [dim, setDim] = useState<DecomposeDimension>('VENDOR')
  const [decompose, setDecompose] = useState<DecomposeResponse | null>(null)
  const [whyContributors, setWhyContributors] = useState<string | null>(null)
  const [escalating, setEscalating] = useState(false)
  const [escalateError, setEscalateError] = useState<string | null>(null)
  const [escalateResult, setEscalateResult] = useState<DispatchAudienceResult[] | null>(null)

  useEffect(() => {
    let ignore = false
    // /decompose is landing on the service -- a 404 (today, always) comes
    // back as `null` from decomposeFinding, and the "Why" column just
    // falls back to the cause phrase below. This is not an error state.
    // oxlint-disable-next-line react/set-state-in-effect
    decomposeFinding(finding.id, 'VENDOR').then((result) => {
      // Defensive against a malformed/unexpected response shape too, not
      // just the documented "not implemented" 404 -- `rows` missing
      // entirely must not crash this card.
      if (ignore || !result || !Array.isArray(result.rows) || result.rows.length === 0) return
      // "Pooja Sokolov Travel owns 4.1 pts, Vikram Mikhailov Travel 1.3
      // pts" -- the verb only needs saying once.
      const top2 = result.rows
        .slice(0, 2)
        .map((row, index) =>
          index === 0 ? `${row.label} owns ${row.pointsOfGap.toFixed(1)} pts` : `${row.label} ${row.pointsOfGap.toFixed(1)} pts`,
        )
        .join(', ')
      setWhyContributors(top2)
    })
    return () => {
      ignore = true
    }
  }, [finding.id])

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

  const totalTrips =
    decompose && Array.isArray(decompose.rows) ? decompose.rows.reduce((sum, row) => sum + row.n, 0) : null

  return (
    <Card className={`priority-card priority-card--${finding.tier.toLowerCase()}`}>
      <div className="priority-card__stripe" aria-hidden="true" />
      <div className="priority-card__body">
        <div className="priority-card__header">
          <h3 className="priority-card__title">
            {finding.metricLabel} — {formatSliceLabel(finding.sliceLabel)}
          </h3>
          <TierBadge tier={finding.tier} />
        </div>

        <p className="priority-card__sentence">{buildFindingSentence(finding)}</p>

        <div className="priority-card__columns">
          <div className="priority-card__column">
            <h4>Why</h4>
            <p>{whyContributors ?? causePhrase(finding.cause)}</p>
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
            {finding.action && <p className="priority-card__action">Action: {finding.action}</p>}
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
