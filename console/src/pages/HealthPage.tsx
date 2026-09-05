import { label } from '../api/labels.ts'
import type { FeedHealth } from '../api/types.ts'
import { FeedHealthStrip } from '../components/FeedHealthStrip.tsx'

export function HealthPage({ feeds }: { feeds: FeedHealth[] }) {
  const feedsWithQuirks = feeds.filter((feed) => feed.quirks && feed.quirks.length > 0)

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

      {/* Landing on the service partition -- feature-detected: a feed with
          no `quirks` renders nothing here, not an empty heading. The demo
          beat: here is what the data does that we noticed and handled. */}
      {feedsWithQuirks.length > 0 && (
        <div className="health-quirks">
          <h2 className="panel-heading">What we noticed and handled</h2>
          {feedsWithQuirks.map((feed) => (
            <div key={feed.feed} className="health-quirks__feed">
              <h3>{label('feed', feed.feed)}</h3>
              <ul>
                {feed.quirks!.map((quirk) => (
                  <li key={quirk.name}>
                    <strong>{quirk.name}</strong>: {quirk.rows.toLocaleString()} rows -- {quirk.detail}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}
