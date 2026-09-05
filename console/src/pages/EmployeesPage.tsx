import { useEffect, useState } from 'react'
import { getCapabilities, getEmployeeImpact, hasCapability } from '../api/client.ts'
import { label } from '../api/labels.ts'
import type { EmployeeImpact, EmployeeImpactCounts } from '../api/types.ts'
import { NOT_MEASURED } from '../api/types.ts'
import { Card } from '../components/Card.tsx'

// en-IN grouping throughout, exactly as HealthPage does -- an India-based
// commute product, and an explicit locale keeps the rendering identical
// regardless of the deployment environment's own default.
function count(value: number): string {
  return value.toLocaleString('en-IN')
}

// A minute reading the service already rounded. Null means the window had
// nothing to measure -- that is not zero minutes, so it renders as the
// shared NOT_MEASURED dash rather than an alarming "0 min".
function minutes(value: number | null): string {
  return value === null ? NOT_MEASURED : `${value} min`
}

// cost_per_rider's unit is INR (registry.py); ₹ prefix matches CostMeter
// and the rest of the console.
function rupees(value: number | null): string {
  return value === null ? NOT_MEASURED : `₹${value}`
}

// The served share (0..1) rendered in percent. A unit render of one API
// number -- nothing is combined, averaged or derived here.
function share(value: number | null): string {
  return value === null ? NOT_MEASURED : `${(value * 100).toFixed(1)}%`
}

interface Stat {
  title: string
  value: string
  detail?: string
}

function StatCard({ stat }: { stat: Stat }) {
  return (
    <Card className="impact-stat">
      <h2 className="impact-stat__title">{stat.title}</h2>
      <p className="impact-stat__value num">{stat.value}</p>
      {stat.detail && <p className="impact-stat__detail">{stat.detail}</p>}
    </Card>
  )
}

interface ImpactTableRow {
  key: string
  name: string
  counts: EmployeeImpactCounts
}

// One definition per column, reused for the header text and its tooltip --
// the same convention FindingsList uses.
const COLUMNS: { label: string; title: string }[] = [
  { label: 'Employees hit', title: 'Distinct employees with a no-show or a late pickup in this window' },
  { label: 'Late pickups', title: 'Legs picked up later than the on-time grace allows' },
  { label: 'No-shows', title: 'Legs where the employee did not board' },
  { label: 'Legs', title: 'All employee legs measured for this row' },
]

// Rendered exactly in the order the service returned (bySite/byVendor are
// already its top-10 by employees impacted) -- this never re-sorts and
// never truncates.
function ImpactTable({ title, what, rows }: { title: string; what: string; rows: ImpactTableRow[] }) {
  return (
    <div className="impact-breakdown">
      <h2 className="panel-heading">{title}</h2>
      {rows.length === 0 ? (
        <p className="impact-breakdown__empty">No {what} in this window.</p>
      ) : (
        <table className="impact-table">
          <thead>
            <tr>
              <th scope="col">{what.charAt(0).toUpperCase() + what.slice(1)}</th>
              {COLUMNS.map((column) => (
                <th key={column.label} scope="col" title={column.title} className="num">
                  {column.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.key}>
                <th scope="row">{row.name}</th>
                <td className="num">{count(row.counts.impacted)}</td>
                <td className="num">{count(row.counts.latePickups)}</td>
                <td className="num">{count(row.counts.noShows)}</td>
                <td className="num">{count(row.counts.legs)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

type Status = 'loading' | 'absent' | 'error' | 'ready'

// Who the commute failures actually hit, and where. Every figure comes
// from GET /api/employees/impact -- the console derives none of them.
//
// The endpoint is optional, so this feature-detects off /api/health's
// `capabilities` list ("employees") rather than by calling it and reading
// a failure as absence. An absent endpoint is an honest empty state; a
// call that fails for any other reason is an error, and the two never get
// confused (see Part A).
export function EmployeesPage({ runId }: { runId: string }) {
  const [status, setStatus] = useState<Status>('loading')
  const [impact, setImpact] = useState<EmployeeImpact | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let ignore = false
    // oxlint-disable-next-line react/set-state-in-effect
    getCapabilities()
      .then(async (capabilities) => {
        if (!hasCapability(capabilities, 'employees')) {
          if (!ignore) setStatus('absent')
          return
        }
        const result = await getEmployeeImpact(runId)
        if (ignore) return
        setImpact(result)
        setStatus('ready')
      })
      .catch((err: unknown) => {
        if (ignore) return
        setError(err instanceof Error ? err.message : String(err))
        setStatus('error')
      })
    return () => {
      ignore = true
    }
  }, [runId])

  if (status === 'loading') {
    return (
      <section>
        <h1 className="page-heading">Employee impact</h1>
        <p className="console__status">Loading…</p>
      </section>
    )
  }

  if (status === 'absent') {
    return (
      <section>
        <h1 className="page-heading">Employee impact</h1>
        <p className="impact-absent">Employee impact is not available on this build.</p>
      </section>
    )
  }

  if (status === 'error' || impact === null) {
    return (
      <section>
        <h1 className="page-heading">Employee impact</h1>
        <p className="console__status console__status--error">{error}</p>
      </section>
    )
  }

  const stats: Stat[] = [
    {
      title: 'Employees hit',
      value: count(impact.employeesImpacted),
      detail: `of ${count(impact.ridersInWindow)} riders in this window`,
    },
    { title: 'Late pickups', value: count(impact.latePickupLegs), detail: 'legs' },
    { title: 'No-shows', value: count(impact.noShowLegs), detail: 'legs' },
    {
      title: 'Average pickup delay',
      value: minutes(impact.avgPickupDelayMin),
      detail: `median ${minutes(impact.medianPickupDelayMin)}`,
    },
    {
      title: 'Cost per rider',
      value: rupees(impact.costPerRider),
      detail: `4-week average ${rupees(impact.costPerRiderTrend)}`,
    },
    {
      title: 'Employee-caused delay',
      value: share(impact.employeeCausedDelayShare),
      detail: 'of delay this window is attributed to the employee, not the ride',
    },
  ]

  const nothingMeasured =
    impact.byShiftBand.length === 0 && impact.bySite.length === 0 && impact.byVendor.length === 0

  return (
    <section>
      <h1 className="page-heading">Employee impact</h1>
      <p className="impact-lede">
        Who the commute failures actually hit, and where — {impact.window.label}.
      </p>

      <div className="impact-stats">
        {stats.map((stat) => (
          <StatCard key={stat.title} stat={stat} />
        ))}
      </div>

      {nothingMeasured ? (
        <p className="impact-breakdown__empty">
          No employee legs were measured for this window, so there is nothing to break down.
        </p>
      ) : (
        <>
          <ImpactTable
            title="Worst shift bands"
            what="shift"
            rows={impact.byShiftBand.map((row) => ({
              key: row.shiftBand,
              name: label('shiftBand', row.shiftBand),
              counts: row,
            }))}
          />
          <ImpactTable
            title="Worst sites"
            what="site"
            rows={impact.bySite.map((row) => ({ key: row.site, name: row.site, counts: row }))}
          />
          <ImpactTable
            title="Worst vendors"
            what="vendor"
            rows={impact.byVendor.map((row) => ({ key: row.vendor, name: row.vendor, counts: row }))}
          />
        </>
      )}
    </section>
  )
}
