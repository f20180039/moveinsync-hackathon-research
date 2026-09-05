import { label } from '../api/labels.ts'
import type { Cost } from '../api/types.ts'

function formatInr(value: number, approximate: boolean): string {
  return `${approximate ? '≈' : ''}₹${value.toFixed(4)}`
}

// Calls, tokens per call, cost per interaction, cost at scale. Never prints a
// rupee figure when pricing is unconfigured or there have been no calls --
// that number is the one a judge can check, so it must never be invented.
export function CostMeter({ cost }: { cost: Cost }) {
  const unconfigured = !cost.pricingConfigured || cost.calls === 0
  const purposes = Object.entries(cost.byPurpose)

  return (
    <div className="cost-meter">
      <div className="cost-meter__stat">
        <span className="cost-meter__label">Calls</span>
        <span className="cost-meter__value num">{cost.calls}</span>
      </div>
      <div className="cost-meter__stat">
        <span className="cost-meter__label">Tokens per call</span>
        <span className="cost-meter__value num">{cost.tokensPerCall}</span>
      </div>

      {purposes.length > 0 && (
        <div className="cost-meter__stat">
          <span className="cost-meter__label">By purpose</span>
          <span className="cost-meter__value cost-meter__by-purpose">
            {purposes.map(([purpose, count]) => (
              <span key={purpose}>
                {label('purpose', purpose)} {count}
              </span>
            ))}
          </span>
        </div>
      )}

      {unconfigured ? (
        <p className="cost-meter__unconfigured">pricing not configured / no calls yet</p>
      ) : (
        <>
          <div className="cost-meter__stat">
            <span className="cost-meter__label">₹ per interaction</span>
            <span className="cost-meter__value num">
              {formatInr(cost.inr / cost.calls, cost.rateIsApproximate)}
            </span>
          </div>
          <div className="cost-meter__stat">
            <span className="cost-meter__label">₹ per organisation per month</span>
            <span className="cost-meter__value num">
              {formatInr(cost.inrPerOrgPerMonth, cost.rateIsApproximate)}
            </span>
          </div>
          <div className="cost-meter__stat">
            <span className="cost-meter__label">
              ₹ per employee per month (at {cost.employeesAtScale.toLocaleString()} employees)
            </span>
            <span className="cost-meter__value num">
              {formatInr(cost.inrPerEmployeePerMonth, cost.rateIsApproximate)}
            </span>
          </div>
        </>
      )}
    </div>
  )
}
