/**
 * PURPOSE: de-prioritise zones where the admin keeps rejecting our suggestions.
 * PIVOT: this is the feedback loop — wire admin Reject into ctx.zoneRejections
 *        and the engine learns. Never make it a block.
 * SAFE-TO-DELETE: yes — the engine works without it, but the loop is a good
 *                 demo beat (PRD edge case 9).
 */
import type { Policy } from '../types'
import { pass, verdict } from '../policy'

export const REJECTION_THRESHOLD = 3

export const zoneConfidence: Policy = (c, _w, ctx) => {
  const id = 'zone-confidence'
  const name = 'Zone confidence'
  const zoneIds = [...new Set(c.trips.map((t) => t.zoneId))]
  const worst = zoneIds.reduce((max, z) => Math.max(max, ctx.zoneRejections[z] ?? 0), 0)

  return worst < REJECTION_THRESHOLD
    ? pass(id, name, `Zone confidence normal (${worst} prior rejections)`,
        { value: REJECTION_THRESHOLD - worst, unit: 'rejections' })
    : verdict(id, name, 'soft', 'low_confidence',
        `Admin rejected ${worst} suggestions in this zone — de-prioritising`,
        { value: REJECTION_THRESHOLD - worst, unit: 'rejections' })
}
