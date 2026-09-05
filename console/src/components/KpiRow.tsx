import { findOverall } from '../api/insights.ts'
import type { Finding } from '../api/types.ts'
import { KpiCard } from './KpiCard.tsx'

// The four headline metrics, each looked up as the unsliced ("overall")
// finding for that metric id. Shared by Overview and the weekly/monthly
// review pages so the KPI row never drifts between them.
export function KpiRow({ findings }: { findings: Finding[] }) {
  return (
    <div className="kpi-row">
      <KpiCard title="On-time arrival" finding={findOverall(findings, 'ota')} />
      <KpiCard title="On-time departure" finding={findOverall(findings, 'otd')} />
      <KpiCard title="No-show rate" finding={findOverall(findings, 'no_show_rate')} />
      <KpiCard title="Cost per km" finding={findOverall(findings, 'cost_per_km')} />
    </div>
  )
}
