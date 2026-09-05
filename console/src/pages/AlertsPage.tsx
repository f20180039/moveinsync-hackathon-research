import { useState } from 'react'
import { isDismissed } from '../api/dismissed.ts'
import { groupFindingsByMetric } from '../api/insights.ts'
import type { Finding } from '../api/types.ts'
import { isAlertTier } from '../api/types.ts'
import { PriorityActionCard } from '../components/PriorityActionCard.tsx'
import { SafetyBanner } from '../components/SafetyBanner.tsx'

export interface AlertsPageProps {
  findings: Finding[]
  runId: string | null
}

// The full priority-action card list for every CONCERN/BREACH finding
// (Overview only shows a capped top 5) -- grouped by metric, with a count
// in each group header, so a noisy metric (20 marshal_compliance
// breaches) reads as one group, not 20 flat top-level cards. `findings` is
// already the latest run's findings in server-ranked order -- "newest run
// first" holds trivially today, since the contract only exposes
// `/api/runs/latest/findings` (no multi-run history endpoint yet); this
// will need revisiting once one exists.
export function AlertsPage({ findings, runId }: AlertsPageProps) {
  // Forces a re-render after a Dismiss click so the plain (non-memoized)
  // filter below picks up the updated dismissed-id set in localStorage.
  const [, forceRerender] = useState(0)

  const alerts = findings.filter((f) => isAlertTier(f.tier) && !isDismissed(f.id))
  const groups = groupFindingsByMetric(alerts)

  return (
    <section>
      {runId && <SafetyBanner runId={runId} />}
      {groups.length === 0 ? (
        <p>Nothing above watch needs attention this window.</p>
      ) : (
        groups.map((group) => (
          <div key={group.metricId} className="alerts-group">
            <h2 className="alerts-group__header">
              {group.metricLabel} <span className="alerts-group__count">({group.findings.length})</span>
            </h2>
            <div className="priority-actions__list">
              {group.findings.map(
                (finding) =>
                  runId && (
                    <PriorityActionCard
                      key={finding.id}
                      finding={finding}
                      runId={runId}
                      onDismiss={() => forceRerender((tick) => tick + 1)}
                    />
                  ),
              )}
            </div>
          </div>
        ))
      )}
    </section>
  )
}
