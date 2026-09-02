/**
 * PURPOSE: every pickup must start inside one of its trip's windows.
 * PIVOT: two-tier SLA (FleetPy user_max_wait_time_2, spec 07 §2) plugs in here
 *        as a second, relaxed pass — Tier B.
 * SAFE-TO-DELETE: no.
 */
import type { Policy, Trip } from '../types'
import { pass, verdict } from '../policy'

/** Arriving more than this many minutes before the window opens is a soft miss. */
export const LEAD_TIME_TOLERANCE_MIN = 15

const MS_PER_MIN = 60_000

function earliestStart(t: Trip): number {
  return Math.min(...t.windows.map((wnd) => wnd[0]))
}
function insideAnyWindow(t: Trip, at: number): boolean {
  return t.windows.some((wnd) => at >= wnd[0] && at <= wnd[1])
}

export const timeWindow: Policy = (c) => {
  const id = 'time-window'
  const name = 'Pickup window'

  let worstLateMin = 0
  let lateTripId = ''
  let worstEarlyMin = 0
  let earlyTripId = ''

  for (const t of c.trips) {
    const at = c.pickupTimes[t.id]
    if (at === undefined || t.windows.length === 0) continue
    if (insideAnyWindow(t, at)) continue

    // Outside every window. Which kind of violation depends on WHERE:
    // if any window has already closed, the pickup is late relative to the most
    // recently closed one; otherwise it is before all windows and merely early.
    //
    // This must NOT be written as `at > latestEnd(t)`. A pickup in a GAP between
    // two windows is after neither the latest end nor before the earliest start,
    // so that formulation falls through to pass() and silently approves a pickup
    // that satisfies no window at all.
    const closedEnds = t.windows.map((wnd) => wnd[1]).filter((end) => end < at)

    if (closedEnds.length > 0) {
      const lastClosed = Math.max(...closedEnds)
      const lateMin = (at - lastClosed) / MS_PER_MIN
      if (lateMin > worstLateMin) { worstLateMin = lateMin; lateTripId = t.id }
    } else {
      const earlyMin = (earliestStart(t) - at) / MS_PER_MIN
      if (earlyMin > worstEarlyMin) { worstEarlyMin = earlyMin; earlyTripId = t.id }
    }
  }

  if (worstLateMin > 0) {
    return verdict(id, name, 'block', 'delay',
      `${lateTripId} would be picked up ${worstLateMin.toFixed(0)} min after its window closes`,
      { value: -worstLateMin, unit: 'min' })
  }
  if (worstEarlyMin > LEAD_TIME_TOLERANCE_MIN) {
    return verdict(id, name, 'soft', 'lead_time',
      `${earlyTripId} would wait ${worstEarlyMin.toFixed(0)} min before its window opens`,
      { value: -(worstEarlyMin - LEAD_TIME_TOLERANCE_MIN), unit: 'min' })
  }
  return pass(id, name, 'All pickups inside their windows')
}
