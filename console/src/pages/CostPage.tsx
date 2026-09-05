import type { Cost } from '../api/types.ts'
import { CostMeter } from '../components/CostMeter.tsx'

export function CostPage({ cost }: { cost: Cost }) {
  return (
    <section>
      <h1 className="page-heading">Cost</h1>
      <CostMeter cost={cost} />
      {cost.pricingConfigured && cost.calls > 0 && (
        <p className="cost-explainer">
          The extrapolation: the measured ₹ cost for this run is scaled to a month, then spread
          across {cost.employeesAtScale.toLocaleString()} employees -- ₹ per organisation per
          month ÷ employees at scale = ₹ per employee per month.
          {cost.rateIsApproximate && ' Every ₹ figure here is approximate (±17%).'}
        </p>
      )}
    </section>
  )
}
