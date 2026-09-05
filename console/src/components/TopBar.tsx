import { useLocation } from 'react-router-dom'
import { titleFor } from '../nav.ts'
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

// Persists across every route. The heading is the CURRENT PAGE'S OWN NAME,
// resolved from the same nav table the sidebar renders (nav.ts) -- a raw run
// id is not a page title, and reading "run run-1785542400000-b0" told a
// viewer nothing about where they were. The run and its window are still
// here, demoted to the provenance line they always were: which sweep these
// numbers came from, in smaller, quieter type underneath.
export function TopBar({ runId, windowLabel, onSweep, sweeping, role, onRoleChange }: TopBarProps) {
  const title = titleFor(useLocation().pathname)

  return (
    <header className="top-bar">
      <div className="top-bar__heading">
        <h1 className="top-bar__title">{title ?? 'Signal Desk'}</h1>
        <span className="top-bar__run">
          {windowLabel && runId ? `${windowLabel} · ${runId}` : 'Loading…'}
        </span>
      </div>
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
