import { Link } from 'react-router-dom'
import type { Cost, Finding } from '../api/types.ts'
import { FindingsList } from '../components/FindingsList.tsx'

// The default route. A condensed summary strip stands in for the old
// combined control strip -- the actual brief and cost controls now live on
// their own routes -- so a first-time visitor still sees at a glance that
// they exist, without either one crowding the findings themselves.
export function FindingsPage({ cost, findings }: { cost: Cost | null; findings: Finding[] }) {
  return (
    <>
      <div className="summary-strip" data-testid="summary-strip">
        <div className="summary-tile">
          <h2 className="panel-heading">Brief &amp; dispatch</h2>
          <p>Preview a brief for any audience and send it to Slack/email.</p>
          <Link className="btn btn--secondary btn--sm" to="/brief">
            Go to Brief
          </Link>
        </div>

        <div className="summary-tile">
          <h2 className="panel-heading">Cost</h2>
          {cost && (
            <div className="summary-tile__stats num">
              <span>{cost.calls} calls</span>
              <span>{cost.tokensPerCall} tokens/call</span>
            </div>
          )}
          <Link className="btn btn--secondary btn--sm" to="/cost">
            Go to Cost
          </Link>
        </div>
      </div>

      <section className="findings-section" data-testid="findings-section">
        <h1 className="page-heading">Findings</h1>
        <FindingsList findings={findings} />
      </section>
    </>
  )
}
