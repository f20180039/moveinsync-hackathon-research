/**
 * PURPOSE: a merged cab may serve at most MAX_GATES distinct office gates.
 * PIVOT: raise MAX_GATES only with EXTRA_MIN_PER_GATE fed into detour-sla, or
 *        the SLA silently absorbs the cost.
 * SAFE-TO-DELETE: no — this is what keeps login trips a single-destination
 *                 problem, which is why brute-force pickup ordering stays exact.
 */
import type { Policy } from '../types'
import { pass, verdict } from '../policy'

export const MAX_GATES = 2
/** Minutes added per gate beyond the first. */
export const EXTRA_MIN_PER_GATE = 5

export const gateSpread: Policy = (c) => {
  const id = 'gate-spread'
  const name = 'Gate spread'
  const distinct = [...new Set(c.gateIds)]
  const extraMin = Math.max(0, distinct.length - 1) * EXTRA_MIN_PER_GATE

  return distinct.length <= MAX_GATES
    ? pass(id, name,
        `${distinct.length} gate${distinct.length === 1 ? '' : 's'}, +${extraMin} min`,
        { value: -extraMin || 0, unit: 'min' })
    : verdict(id, name, 'block', 'max_tasks',
        `${distinct.length} distinct gates exceeds the limit of ${MAX_GATES}`,
        { value: -extraMin || 0, unit: 'min' })
}
