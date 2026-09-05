import { Button } from './Button.tsx'
import { Legend } from './Legend.tsx'

export interface TopBarProps {
  runId: string | null
  windowLabel: string | null
  onSweep: () => void
  sweeping: boolean
}

// Persists across every route: run id + window label on the left, the
// legend trigger ("How to read this") and Sweep now on the right.
export function TopBar({ runId, windowLabel, onSweep, sweeping }: TopBarProps) {
  return (
    <header className="top-bar">
      <span className="top-bar__run">
        {windowLabel && runId ? (
          <>
            {windowLabel} · run {runId}
          </>
        ) : (
          'Loading…'
        )}
      </span>
      <div className="top-bar__actions">
        <Legend />
        <Button onClick={onSweep} busy={sweeping}>
          Sweep now
        </Button>
      </div>
    </header>
  )
}
