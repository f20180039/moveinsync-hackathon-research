// Stage 1: the greeting band only (the shell). KPI cards, peer context and
// priority actions land in Stage 2, on top of this same page.
export function OverviewPage({ windowLabel }: { windowLabel: string | null }) {
  return (
    <div className="greeting-band">
      <h1>Here's what needs your attention</h1>
      <p>{windowLabel ?? 'Loading the current window…'}</p>
    </div>
  )
}
