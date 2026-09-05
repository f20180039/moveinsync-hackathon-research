import type { FeedHealth } from '../api/types.ts'
import { FeedHealthStrip } from '../components/FeedHealthStrip.tsx'

export function HealthPage({ feeds }: { feeds: FeedHealth[] }) {
  return (
    <section>
      <h1 className="page-heading">Feed health</h1>
      <FeedHealthStrip feeds={feeds} />
      <dl className="health-definitions">
        <dt>Quarantined</dt>
        <dd>Rows the sweep rejected outright -- malformed or unreadable.</dd>
        <dt>Unmatched</dt>
        <dd>Rows that couldn't be joined to their key in another feed.</dd>
        <dt>Confidence</dt>
        <dd>The share of this feed's rows we trust for the window -- below 90% is flagged.</dd>
      </dl>
    </section>
  )
}
