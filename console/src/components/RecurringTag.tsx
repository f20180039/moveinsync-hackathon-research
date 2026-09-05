import { isRecurring } from '../api/insights.ts'
import type { Finding } from '../api/types.ts'

// A muted outline tag (no new saturated colour -- same "severity in form,
// not colour alone" rule as TierBadge) shown once the same slice has been
// Concern or worse in at least RECURRING_THRESHOLD_WEEKS of the last
// `recurrence.of` windows. `recurrence` is optional and landing on the
// service partition (Task 16) -- feature-detected: absent, or below
// threshold, renders nothing.
export function RecurringTag({ finding }: { finding: Finding }) {
  if (!finding.recurrence || !isRecurring(finding)) return null

  const { weeks, of } = finding.recurrence

  return (
    <span className="recurring-tag">
      Recurring · {weeks} of the last {of} weeks
    </span>
  )
}
