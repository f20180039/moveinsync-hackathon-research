import type { FeedHealth } from '../api/types.ts'
import { shouldDiscloseConfidence } from '../api/types.ts'

// A row we could not read is a finding, not a log line -- quarantined and
// unmatched counts are numbers on screen, never a tooltip.
export function FeedHealthStrip({ feeds }: { feeds: FeedHealth[] }) {
  return (
    <table className="feed-health-strip">
      <caption>Feed health</caption>
      <thead>
        <tr>
          <th scope="col">Feed</th>
          <th scope="col">Rows loaded</th>
          <th scope="col">Quarantined</th>
          <th scope="col">Unmatched</th>
          <th scope="col">Confidence</th>
        </tr>
      </thead>
      <tbody>
        {feeds.map((feed) => {
          const flagged = shouldDiscloseConfidence(feed.confidence)
          return (
            <tr key={feed.feed} className={flagged ? 'feed-health-strip__row--flagged' : undefined}>
              <th scope="row">{feed.feed}</th>
              <td>{feed.rowsLoaded}</td>
              <td className={feed.rowsRejected > 0 ? 'feed-health-strip__quarantined' : undefined}>
                {feed.rowsRejected}
              </td>
              <td>{feed.unmatchedKeys}</td>
              <td>
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
