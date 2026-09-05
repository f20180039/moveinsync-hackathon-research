import type { Finding } from '../api/types.ts'
import { FindingsList } from '../components/FindingsList.tsx'

const VENDOR_PREFIX = 'vendor '

// Findings sliced by vendor, grouped so a transport manager can see every
// finding for one vendor together rather than hunting through the full
// findings table.
export function VendorsPage({ findings }: { findings: Finding[] }) {
  const groups = new Map<string, Finding[]>()
  for (const finding of findings) {
    if (!finding.sliceLabel.startsWith(VENDOR_PREFIX)) continue
    const vendor = finding.sliceLabel.slice(VENDOR_PREFIX.length)
    const group = groups.get(vendor) ?? []
    group.push(finding)
    groups.set(vendor, group)
  }

  return (
    <section>
      <h1 className="page-heading">Vendors</h1>
      {groups.size === 0 ? (
        <p>No vendor-level findings in this window.</p>
      ) : (
        <div className="vendor-groups">
          {Array.from(groups.entries()).map(([vendor, vendorFindings]) => (
            <div key={vendor} className="vendor-group">
              <h2 className="panel-heading">{vendor}</h2>
              <FindingsList findings={vendorFindings} />
            </div>
          ))}
        </div>
      )}
    </section>
  )
}
