import type { Finding } from '../api/types.ts'
import { isAlertTier } from '../api/types.ts'
import { FindingsList } from '../components/FindingsList.tsx'

// Stage 1 stub: findings at CONCERN/BREACH shown via the existing findings
// table, just to make the route and the sidebar badge real. Stage 3
// replaces the body with the full priority-action card list.
export function AlertsPage({ findings }: { findings: Finding[] }) {
  const alerts = findings.filter((f) => isAlertTier(f.tier))

  return (
    <section>
      <h1 className="page-heading">Alerts</h1>
      <FindingsList findings={alerts} />
    </section>
  )
}
