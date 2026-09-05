import { useEffect, useState } from 'react'
import { getCapabilities, getShiftOutlook, hasCapability } from '../api/client.ts'
import { formatSliceLabel, label } from '../api/labels.ts'
import type { OutlookProjection, ShiftOutlook } from '../api/types.ts'
import { NOT_MEASURED, formatMetricValue } from '../api/types.ts'
import { Card } from './Card.tsx'

type Status = 'loading' | 'absent' | 'error' | 'ready'

function value(v: number | null, unit: string): string {
  return v === null ? NOT_MEASURED : formatMetricValue(v, unit)
}

// A withheld projection is a stated refusal: the service says how many of
// its basis days had data and declines to put a number on it. It is not an
// error and it is emphatically not a zero.
function Row({ projection }: { projection: OutlookProjection }) {
  const readiness = label('readiness', projection.readiness)
  return (
    <tr>
      <th scope="row">{formatSliceLabel(projection.slice)}</th>
      <td>
        <span className={`outlook-readiness outlook-readiness--${projection.readiness.toLowerCase()}`}>
          {readiness}
        </span>
      </td>
      <td className="num">{value(projection.projected, projection.unit)}</td>
      <td className="num">
        {projection.intervalLow === null || projection.intervalHigh === null
          ? NOT_MEASURED
          : `${value(projection.intervalLow, projection.unit)} – ${value(projection.intervalHigh, projection.unit)}`}
      </td>
      <td>{projection.withheld ? projection.note || projection.action : projection.action}</td>
    </tr>
  )
}

export interface ShiftOutlookCardProps {
  runId: string
  /** The service's own ?date=YYYY-MM-DD steering. Empty means "let the
   * service pick its default target day" -- the console never invents one. */
  date?: string
}

// Shift readiness for the next same-weekday window, from
// GET /api/outlook/shifts. Renders NOTHING when the build does not
// advertise the "outlook" capability, so an older service simply doesn't
// show the card rather than showing an error.
export function ShiftOutlookCard({ runId, date }: ShiftOutlookCardProps) {
  const [status, setStatus] = useState<Status>('loading')
  const [outlook, setOutlook] = useState<ShiftOutlook | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [targetDate, setTargetDate] = useState(date ?? '')

  useEffect(() => {
    let ignore = false
    // oxlint-disable-next-line react/set-state-in-effect
    getCapabilities()
      .then(async (capabilities) => {
        if (!hasCapability(capabilities, 'outlook')) {
          if (!ignore) setStatus('absent')
          return
        }
        const result = await getShiftOutlook(runId, targetDate || undefined)
        if (ignore) return
        setOutlook(result)
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
  }, [runId, targetDate])

  // An absent optional endpoint is not a hole on the page -- it is no card.
  if (status === 'absent') return null

  return (
    <Card className="outlook-card">
      <h2 className="panel-heading">Shift readiness outlook</h2>

      <div className="outlook-card__controls">
        <label className="field__label" htmlFor="outlook-date">
          Target date
        </label>
        <input
          id="outlook-date"
          className="outlook-card__date"
          type="date"
          value={targetDate}
          onChange={(event) => setTargetDate(event.target.value)}
        />
      </div>

      {status === 'loading' && <p className="console__status">Loading…</p>}
      {status === 'error' && <p className="console__status console__status--error">{error}</p>}

      {status === 'ready' && outlook !== null && (
        <>
          <p className="outlook-card__method">
            {/* Stated in the UI, not buried: this is a same-weekday
                baseline over the service's own basisWeeks, not a forecast
                model. Every number below is the service's. */}
            Same-weekday baseline over the last {outlook.basisWeeks} weeks
            {outlook.targetDate ? ` for ${outlook.targetDate}` : ''} — a stated baseline, not a prediction.
          </p>

          {outlook.shifts.length === 0 ? (
            <p className="outlook-card__empty">No shift bands to project for this target day.</p>
          ) : (
            <table className="impact-table outlook-table">
              <thead>
                <tr>
                  <th scope="col">Shift</th>
                  <th scope="col" title="A rename of the verdict tier this projection lands in">
                    Readiness
                  </th>
                  <th scope="col" className="num" title="The service's projected value for the target day">
                    Projected
                  </th>
                  <th scope="col" className="num" title="The range the service states around it">
                    Range
                  </th>
                  <th scope="col">What to do</th>
                </tr>
              </thead>
              <tbody>
                {outlook.shifts.map((projection) => (
                  <Row key={projection.slice} projection={projection} />
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </Card>
  )
}
