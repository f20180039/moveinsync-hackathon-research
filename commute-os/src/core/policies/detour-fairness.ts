/**
 * PURPOSE: stop the same employee absorbing the pooling detour every day.
 * PIVOT: if the statement is about adoption or employee experience, promote
 *        this to the hero policy — it is the differentiator.
 * SAFE-TO-DELETE: no. Optimise pure cost and the same unlucky employee in the
 *   far corner takes the hit daily, because the geometry that made them
 *   expensive yesterday is unchanged today. That is how a corporate pooling
 *   programme actually dies, and no cost-only optimiser can see it.
 *   (spec 08 §3, Timefold's load-balancing constraint.)
 */
import type { Policy } from '../types'
import { pass, verdict } from '../policy'

/** Minutes of detour one employee should absorb in a week before it is unfair. */
export const FAIR_WEEKLY_DETOUR_MIN = 90

export const detourFairness: Policy = (c, w, ctx) => {
  const id = 'detour-fairness'
  const name = 'Detour fairness'

  // Every employee in the candidate, at zero prior load if unseen — the
  // .complement() lesson: measuring fairness only over the already-burdened
  // makes "fair" mean "fair among the unlucky".
  const employeeIds = [...new Set(c.trips.flatMap((t) => t.employeeIds))]

  let worst = 0
  let worstId = ''
  for (const eid of employeeIds) {
    const total = (ctx.detourMinutesThisWeek[eid] ?? 0) + (c.perPassengerAddedMin[eid] ?? 0)
    if (total > worst) { worst = total; worstId = eid }
  }

  const spare = FAIR_WEEKLY_DETOUR_MIN - worst
  if (spare >= 0) {
    return pass(id, name,
      `Heaviest detour load ${worst.toFixed(0)} of ${FAIR_WEEKLY_DETOUR_MIN} min/week`,
      { value: spare, unit: 'min/week' })
  }

  const who = w.employees.find((e) => e.id === worstId)?.name ?? worstId
  return verdict(id, name, 'soft', 'unfair_detour',
    `${who} would absorb ${worst.toFixed(0)} min of detour this week, ` +
    `${Math.abs(spare).toFixed(0)} over a fair share`,
    { value: spare, unit: 'min/week' })
}
