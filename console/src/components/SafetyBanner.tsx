import { useEffect, useState } from 'react'
import { getSafety } from '../api/client.ts'
import { label } from '../api/labels.ts'
import type { SafetySummary } from '../api/types.ts'

// A one-line safety banner under the KPI row (Overview and Alerts) --
// landing on the service partition, shape unconfirmed, so this is
// feature-detected: absent/404 renders nothing, not an error or a
// placeholder.
export function SafetyBanner({ runId }: { runId: string }) {
  const [safety, setSafety] = useState<SafetySummary | null>(null)

  useEffect(() => {
    let ignore = false
    // oxlint-disable-next-line react/set-state-in-effect
    getSafety(runId).then((result) => {
      if (!ignore) setSafety(result)
    })
    return () => {
      ignore = true
    }
  }, [runId])

  // Defensive against a malformed/unexpected response shape too, not just
  // the documented "not implemented" 404 (the shape isn't confirmed yet).
  if (!safety || typeof safety.metric !== 'string' || typeof safety.trips !== 'number') return null

  return (
    <p className="safety-banner">
      Safety: MoveInSync raised {label('safetyMetric', safety.metric)} on {safety.trips} trips this week; an escort
      was present on {safety.escortPresentPct}%.
    </p>
  )
}
