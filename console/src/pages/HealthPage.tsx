import { Link } from 'react-router-dom'
import { label } from '../api/labels.ts'
import type { FeedHealth } from '../api/types.ts'
import { FeedHealthStrip } from '../components/FeedHealthStrip.tsx'

export function HealthPage({ feeds }: { feeds: FeedHealth[] }) {
  const feedsWithQuirks = feeds.filter((feed) => feed.quirks && feed.quirks.length > 0)

  return (
    <section>
      <FeedHealthStrip feeds={feeds} />
      <dl className="health-definitions">
        <dt>Quarantined</dt>
        <dd>Rows the sweep rejected outright -- malformed or unreadable.</dd>
        <dt>Unmatched</dt>
        <dd>Rows that couldn't be joined to their key in another feed.</dd>
        <dt>Confidence</dt>
        <dd>The share of this feed's rows we trust for the window -- below 90% is flagged.</dd>
      </dl>

      {/* /cost is no longer a sidebar link, but it is where the model
          cost and the measured query/sweep/model latency live -- evidence
          this page's readers are exactly the ones who go looking for. One
          line, pointing at the panel that already exists. */}
      <p className="health-cost-link">
        <Link to="/cost">Model cost &amp; measured latency</Link>
      </p>

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
                    {/* en-IN explicitly, not the runtime default locale --
                        this is an India-based commute-data product (₹
                        already throughout), so the lakh/crore grouping
                        (247,914 -> 2,47,914) is the deliberate choice, and
                        an explicit locale keeps it identical regardless of
                        the deployment environment's own default locale. */}
                    <strong>{quirk.name}</strong>: {quirk.rows.toLocaleString('en-IN')} rows -- {quirk.detail}
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
