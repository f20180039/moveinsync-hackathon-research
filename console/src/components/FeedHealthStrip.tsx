import { label } from '../api/labels.ts'
import type { FeedHealth } from '../api/types.ts'
import { shouldFlagFeed } from '../api/types.ts'

// A row we could not read is a finding, not a log line -- quarantined and
// unmatched counts are numbers on screen, never a tooltip.
export function FeedHealthStrip({ feeds }: { feeds: FeedHealth[] }) {
  return (
    <table className="feed-health-strip">
      <caption>Feed health</caption>
      <thead>
        <tr>
          <th scope="col">Feed</th>
          <th scope="col" className="num">
            Rows loaded
          </th>
          <th scope="col" className="num">
            Quarantined
          </th>
          <th scope="col" className="num">
            Unmatched
          </th>
          <th scope="col" className="num">
            Confidence
          </th>
        </tr>
      </thead>
      <tbody>
        {feeds.map((feed) => {
          const flagged = shouldFlagFeed(feed)
          return (
            <tr key={feed.feed} className={flagged ? 'feed-health-strip__row--flagged' : undefined}>
              <th scope="row">{label('feed', feed.feed)}</th>
              <td className="num">{feed.rowsLoaded}</td>
              <td
                data-testid="quarantined-count"
                className={`num${feed.rowsRejected > 0 ? ' feed-health-strip__quarantined' : ''}`}
              >
                {feed.rowsRejected}
              </td>
              <td className="num">{feed.unmatchedKeys}</td>
              <td className="num">
                {Math.round(feed.confidence * 100)}%{' '}
                {flagged && <span className="feed-health-strip__flag">⚠ low confidence</span>}
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}
