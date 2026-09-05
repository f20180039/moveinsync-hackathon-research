import { ROLES, ROLE_ORDER } from '../roles.ts'
import type { Role } from '../roles.ts'
import { Button } from './Button.tsx'
import { Legend } from './Legend.tsx'
import { Select } from './Select.tsx'

export interface TopBarProps {
  runId: string | null
  windowLabel: string | null
  onSweep: () => void
  sweeping: boolean
  role: Role
  onRoleChange: (role: Role) => void
}

// Persists across every route: run id + window label on the left, the
// role switcher, legend trigger ("How to read this") and Sweep now on the
// right.
export function TopBar({ runId, windowLabel, onSweep, sweeping, role, onRoleChange }: TopBarProps) {
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
        <Select
          label="Viewing as"
          size="sm"
          value={role}
          onChange={onRoleChange}
          options={ROLE_ORDER.map((id) => ({ value: id, label: ROLES[id].label }))}
        />
        <Legend />
        <Button onClick={onSweep} busy={sweeping}>
          Sweep now
        </Button>
      </div>
    </header>
  )
}
