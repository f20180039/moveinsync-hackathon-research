import { TIER_ORDER } from '../api/types.ts'
import type { Tier } from '../api/types.ts'
import { label, sliceDimensionLabel } from '../api/labels.ts'
import { Select } from './Select.tsx'

export interface MetricOption {
  value: string
  label: string
}

export interface FilterBarProps {
  tiers: Set<Tier>
  onToggleTier: (tier: Tier) => void
  metricId: string
  onMetricChange: (metricId: string) => void
  metricOptions: MetricOption[]
  dimension: string
  onDimensionChange: (dimension: string) => void
  dimensionOptions: string[]
  observedInput: string
  onObservedInputChange: (value: string) => void
  observedHint: string | null
}

// Severity multi-select (checkbox chips), a metric select, a slice-
// dimension select, and the Observed math filter -- every active filter
// composes with AND (see api/filters.ts), so this bar only ever narrows.
export function FilterBar({
  tiers,
  onToggleTier,
  metricId,
  onMetricChange,
  metricOptions,
  dimension,
  onDimensionChange,
  dimensionOptions,
  observedInput,
  onObservedInputChange,
  observedHint,
}: FilterBarProps) {
  return (
    <div className="filter-bar">
      <fieldset className="filter-bar__severity">
        <legend className="field__label">Severity</legend>
        <div className="filter-bar__chips">
          {TIER_ORDER.map((tier) => (
            <label key={tier} className="filter-bar__chip">
              <input
                type="checkbox"
                checked={tiers.has(tier)}
                onChange={() => onToggleTier(tier)}
              />
              {label('tier', tier)}
            </label>
          ))}
        </div>
      </fieldset>

      <Select
        label="Metric"
        value={metricId}
        onChange={onMetricChange}
        options={[{ value: '', label: 'All metrics' }, ...metricOptions]}
      />

      <Select
        label="Slice dimension"
        value={dimension}
        onChange={onDimensionChange}
        options={[
          { value: '', label: 'All dimensions' },
          ...dimensionOptions.map((d) => ({ value: d, label: sliceDimensionLabel(d) })),
        ]}
      />

      <div className="field">
        <label className="field__label" htmlFor="observed-filter">
          Observed
        </label>
        <input
          id="observed-filter"
          className="filter-bar__observed-input"
          type="text"
          placeholder='e.g. "< 60" or "between 40 and 60"'
          value={observedInput}
          onChange={(event) => onObservedInputChange(event.target.value)}
          aria-invalid={observedHint ? true : undefined}
          aria-describedby={observedHint ? 'observed-filter-hint' : undefined}
        />
        {observedHint && (
          <p id="observed-filter-hint" className="filter-bar__hint">
            {observedHint}
          </p>
        )}
      </div>
    </div>
  )
}
