/**
 * PURPOSE: no passenger's journey may grow by more than the SLA allowance.
 * PIVOT: employee SLA is the most politically sensitive number — MAX_DETOUR_MIN
 *        and MAX_DETOUR_FRACTION are the two dials an admin will argue about.
 * SAFE-TO-DELETE: no.
 */
import type { Policy } from '../types'
import { pass, verdict } from '../policy'

/** Absolute ceiling on added travel time for any one passenger. */
export const MAX_DETOUR_MIN = 10
/** Relative ceiling: a short trip may not grow by more than this fraction. */
export const MAX_DETOUR_FRACTION = 0.3

export const detourSla: Policy = (c) => {
  const id = 'detour-sla'
  const name = 'Detour SLA'
  const allowanceMin = Math.min(MAX_DETOUR_MIN, c.minutes * MAX_DETOUR_FRACTION)

  let worst = 0
  let worstWho = ''
  for (const [employeeId, addedMin] of Object.entries(c.perPassengerAddedMin)) {
    if (addedMin > worst) { worst = addedMin; worstWho = employeeId }
  }

  const spare = allowanceMin - worst
  return spare >= 0
    ? pass(id, name,
        `Worst detour ${worst.toFixed(0)} min of ${allowanceMin.toFixed(0)} allowed`,
        { value: spare, unit: 'min' })
    : verdict(id, name, 'block', 'delay',
        `${worstWho} detoured ${worst.toFixed(0)} min, ${allowanceMin.toFixed(0)} allowed`,
        { value: spare, unit: 'min' })
}
