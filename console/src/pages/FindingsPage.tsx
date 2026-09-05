import { useSearchParams } from 'react-router-dom'
import { applyFindingsFilters, parseObservedFilter, sliceDimensionOf } from '../api/filters.ts'
import { paginate } from '../api/pagination.ts'
import type { Finding, Tier } from '../api/types.ts'
import { TIER_ORDER } from '../api/types.ts'
import { FilterBar } from '../components/FilterBar.tsx'
import { FindingsList } from '../components/FindingsList.tsx'
import { Pagination } from '../components/Pagination.tsx'

const PAGE_SIZE = 25
const VALID_TIERS = new Set<string>(TIER_ORDER)

function parseTiers(param: string | null): Set<Tier> {
  if (!param) return new Set()
  return new Set(param.split(',').filter((t) => VALID_TIERS.has(t)) as Tier[])
}

// "Insights" in the sidebar -- the full findings table, with severity /
// metric / dimension / Observed filters (composed with AND) and
// pagination at 25 per page. Every bit of that state lives in the URL
// query string, so a filtered, paged view is a shareable link.
export function FindingsPage({ findings }: { findings: Finding[] }) {
  const [searchParams, setSearchParams] = useSearchParams()

  const tiers = parseTiers(searchParams.get('tiers'))
  const metricId = searchParams.get('metric') ?? ''
  const dimension = searchParams.get('dim') ?? ''
  const observedInput = searchParams.get('observed') ?? ''
  const page = Number.parseInt(searchParams.get('page') ?? '1', 10) || 1

  const parsedObserved = parseObservedFilter(observedInput)
  const observedHint = parsedObserved.ok ? null : parsedObserved.hint

  function updateParams(updates: Record<string, string | null>, resetPage = true) {
    const next = new URLSearchParams(searchParams)
    for (const [key, value] of Object.entries(updates)) {
      if (value === null || value === '') next.delete(key)
      else next.set(key, value)
    }
    if (resetPage) next.delete('page')
    setSearchParams(next)
  }

  function toggleTier(tier: Tier) {
    const next = new Set(tiers)
    if (next.has(tier)) {
      next.delete(tier)
    } else {
      next.add(tier)
    }
    updateParams({ tiers: next.size > 0 ? Array.from(next).join(',') : null })
  }

  const metricOptions = Array.from(new Map(findings.map((f) => [f.metricId, f.metricLabel])).entries()).map(
    ([value, metricLabel]) => ({ value, label: metricLabel }),
  )
  const dimensionOptions = Array.from(new Set(findings.map((f) => sliceDimensionOf(f.sliceLabel))))

  const filtered = applyFindingsFilters(findings, {
    tiers,
    metricId: metricId || null,
    dimension: dimension || null,
    observed: parsedObserved.ok ? parsedObserved.test : null,
  })

  const pageResult = paginate(filtered, page, PAGE_SIZE)

  return (
    <section className="findings-section" data-testid="findings-section">

      <FilterBar
        tiers={tiers}
        onToggleTier={toggleTier}
        metricId={metricId}
        onMetricChange={(value) => updateParams({ metric: value || null })}
        metricOptions={metricOptions}
        dimension={dimension}
        onDimensionChange={(value) => updateParams({ dim: value || null })}
        dimensionOptions={dimensionOptions}
        observedInput={observedInput}
        onObservedInputChange={(value) => updateParams({ observed: value || null })}
        observedHint={observedHint}
      />

      {filtered.length === 0 ? (
        <p className="findings-list__empty">No findings match these filters.</p>
      ) : (
        <>
          <FindingsList findings={pageResult.items} />
          <Pagination page={pageResult} onPageChange={(nextPage) => updateParams({ page: String(nextPage) }, false)} />
        </>
      )}
    </section>
  )
}
