import { useState } from 'react'
import { isDismissed } from '../api/dismissed.ts'
import type { Finding } from '../api/types.ts'
import { isAlertTier } from '../api/types.ts'
import { PriorityActionCard } from '../components/PriorityActionCard.tsx'

export interface AlertsPageProps {
  findings: Finding[]
  runId: string | null
}

// The full priority-action card list for every CONCERN/BREACH finding
// (Overview only shows the top 5). `findings` is already the latest run's
// findings in server-ranked order -- "newest run first" holds trivially
// today, since the contract only exposes `/api/runs/latest/findings` (no
// multi-run history endpoint yet); this will need revisiting once one
// exists.
export function AlertsPage({ findings, runId }: AlertsPageProps) {
  // Forces a re-render after a Dismiss click so the plain (non-memoized)
  // filter below picks up the updated dismissed-id set in localStorage.
  const [, forceRerender] = useState(0)

  const alerts = findings.filter((f) => isAlertTier(f.tier) && !isDismissed(f.id))

  return (
    <section>
      <h1 className="page-heading">Alerts</h1>
      {alerts.length === 0 ? (
        <p>Nothing above watch needs attention this window.</p>
      ) : (
        <div className="priority-actions__list">
          {alerts.map(
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
      )}
    </section>
  )
}
