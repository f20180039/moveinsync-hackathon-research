import { DEFAULT_KPI_METRIC_IDS, findOverall } from '../api/insights.ts'
import { label } from '../api/labels.ts'
import type { Finding } from '../api/types.ts'
import { KpiCard } from './KpiCard.tsx'

// A row of KPI cards, each the unsliced ("overall") finding for a metric
// id -- titles come from label('metric', ...), the one place metric names
// are named, so a role-specific set (Stage 7's persona switch) never
// invents its own wording. A metric with no `overall` finding yet (e.g.
// cost_per_rider, not active on every deployment) renders KpiCard's own
// "Not active yet" placeholder -- the same graceful-absence pattern as
// everywhere else, not a special case here.
export function KpiRow({ findings, metricIds = DEFAULT_KPI_METRIC_IDS }: { findings: Finding[]; metricIds?: string[] }) {
  return (
    <div className="kpi-row">
      {metricIds.map((id) => (
        <KpiCard key={id} title={label('metric', id)} finding={findOverall(findings, id)} />
      ))}
    </div>
  )
}
