import { useState } from 'react'
import { Link } from 'react-router-dom'
import { isDismissed } from '../api/dismissed.ts'
import type { Finding } from '../api/types.ts'
import { isAlertTier } from '../api/types.ts'
import { AskBar } from '../components/AskBar.tsx'
import { KpiRow } from '../components/KpiRow.tsx'
import { PriorityActionCard } from '../components/PriorityActionCard.tsx'

export interface OverviewPageProps {
  windowLabel: string | null
  runId: string | null
  findings: Finding[]
}

// The greeting band (Stage 1) plus, on top of it: four KPI cards (the OTA
// card and its peer/trend context is the demo's core, per the jury
// insight) and the top-5 priority actions. `findings` is already ranked
// worst-first by the server -- filtered and sliced here, never re-sorted.
export function OverviewPage({ windowLabel, runId, findings }: OverviewPageProps) {
  // Triggers a re-render after a Dismiss click, which is all that's needed
  // for the plain (non-memoized) filter below to pick up the updated
  // dismissed-id set in localStorage -- dismissing doesn't change
  // `findings` itself, so nothing else would otherwise cause a re-render.
  const [, forceRerender] = useState(0)

  const priorityFindings = findings.filter((f) => isAlertTier(f.tier) && !isDismissed(f.id)).slice(0, 5)

  return (
    <>
      <div className="greeting-band">
        <h1>Here's what needs your attention</h1>
        <p>{windowLabel ?? 'Loading the current window…'}</p>
      </div>

      <KpiRow findings={findings} />

      <section className="priority-actions" aria-label="Priority actions">
        <div className="priority-actions__header">
          <h2 className="panel-heading">Priority actions</h2>
          <Link to="/alerts" className="priority-actions__view-all">
            View all alerts →
          </Link>
        </div>

        {priorityFindings.length === 0 ? (
          <p>Nothing above watch needs attention this window.</p>
        ) : (
          <div className="priority-actions__list">
            {priorityFindings.map(
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

      {runId && <AskBar runId={runId} />}
    </>
  )
}
