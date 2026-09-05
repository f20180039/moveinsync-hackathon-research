import { isRecurring } from '../api/insights.ts'
import type { Finding } from '../api/types.ts'

export type RecurringTagVariant = 'long' | 'short'

// A muted outline tag (no new saturated colour -- same "severity in form,
// not colour alone" rule as TierBadge) shown once the same slice has been
// Concern or worse in at least RECURRING_THRESHOLD_WEEKS of the last
// `recurrence.of` windows. `recurrence` is optional and landing on the
// service partition (Task 16) -- feature-detected: absent, or below
// threshold, renders nothing.
//
// Two variants: "long" (the priority card's title row, an unconstrained
// flex row that can wrap) spells the sentence out in full; "short" (the
// findings table's Severity cell, a hard-capped grid column) abbreviates
// to "Recurring N/of" with the full sentence moved to the `title`
// attribute, since "Recurring · 3 of the last 4 weeks" (~220-250px at
// 13px) does not fit the column's 132px ceiling and would bleed into the
// Metric column next to it (a visual overflow, not the grid-track
// alignment bug -- .recurring-tag also gets min-width: 0 plus an
// ellipsis fallback as a second line of defence).
export function RecurringTag({ finding, variant = 'long' }: { finding: Finding; variant?: RecurringTagVariant }) {
  if (!finding.recurrence || !isRecurring(finding)) return null

  const { weeks, of } = finding.recurrence
  const fullSentence = `Recurring · ${weeks} of the last ${of} weeks`

  if (variant === 'short') {
    return (
      <span className="recurring-tag recurring-tag--short" title={fullSentence}>
        Recurring {weeks}/{of}
      </span>
    )
  }

  return <span className="recurring-tag">{fullSentence}</span>
}
