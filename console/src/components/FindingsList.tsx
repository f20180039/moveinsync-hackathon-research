import type { Finding } from '../api/types.ts'
import { FindingRow } from './FindingRow.tsx'

// Renders the findings array exactly as the server ranked it. The backend
// enforces the ordering (a BREACH outranks any number of WATCHes; it is
// deliberately not a weighted score), so this never re-sorts.
export function FindingsList({ findings }: { findings: Finding[] }) {
  if (findings.length === 0) {
    return <p className="findings-list__empty">The sweep found nothing above PASS for this window.</p>
  }

  return (
    <ul className="findings-list">
      {findings.map((finding) => (
        <FindingRow key={finding.id} finding={finding} />
      ))}
    </ul>
  )
}
