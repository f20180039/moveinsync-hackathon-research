import type { Finding } from '../api/types.ts'
import { FindingsList } from '../components/FindingsList.tsx'

// "Insights" in the sidebar -- the full findings table. Filters and
// pagination land in Stage 3.
export function FindingsPage({ findings }: { findings: Finding[] }) {
  return (
    <section className="findings-section" data-testid="findings-section">
      <h1 className="page-heading">Insights</h1>
      <FindingsList findings={findings} />
    </section>
  )
}
