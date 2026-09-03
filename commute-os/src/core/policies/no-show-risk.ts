/**
 * PURPOSE: surface the chance that a pooled saving evaporates to a no-show.
 * PIVOT: ctx.noShowOverride is the demo slider; raising it should visibly move
 *        the savings band without changing any merge decision.
 * SAFE-TO-DELETE: yes — but it is what turns a point estimate into a range,
 *                 which is what makes the savings number believable.
 */
import type { Policy } from '../types'
import { pass, verdict } from '../policy'

/** Above this combined probability, warn the admin. */
const RISK_SOFT_THRESHOLD = 0.25

export const noShowRisk: Policy = (c, w, ctx) => {
  const id = 'no-show-risk'
  const name = 'No-show risk'
  const employeeIds = [...new Set(c.trips.flatMap((t) => t.employeeIds))]

  // P(at least one no-show) = 1 - product(1 - p_i)
  let allShow = 1
  for (const eid of employeeIds) {
    const rate = ctx.noShowOverride ?? w.employees.find((e) => e.id === eid)?.noShowRate ?? 0
    allShow *= 1 - rate
  }
  const risk = 1 - allShow
  const pct = risk * 100

  return risk < RISK_SOFT_THRESHOLD
    ? pass(id, name, `${pct.toFixed(0)}% chance of at least one no-show`,
        { value: (RISK_SOFT_THRESHOLD - risk) * 100, unit: '%' })
    : verdict(id, name, 'soft', 'no_show_risk',
        `${pct.toFixed(0)}% chance of at least one no-show — savings may not fully realise`,
        { value: (RISK_SOFT_THRESHOLD - risk) * 100, unit: '%' })
}
