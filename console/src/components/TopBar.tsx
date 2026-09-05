import { useLocation } from 'react-router-dom'
import { titleFor } from '../nav.ts'
import { ROLES, ROLE_ORDER } from '../roles.ts'
import type { Role } from '../roles.ts'
import { Button } from './Button.tsx'
import { Legend } from './Legend.tsx'
import { Select } from './Select.tsx'

export interface TopBarProps {
  onSweep: () => void
  sweeping: boolean
  role: Role
  onRoleChange: (role: Role) => void
}

// Persists across every route. The heading is the CURRENT PAGE'S OWN NAME,
// resolved from the same nav table the sidebar renders (nav.ts), and that
// is all it is. The run id and window used to sit underneath it as a
// provenance line; it was the second thing every viewer read on every
// page, it never changed, and "run-1785542400000-b0" is not information
// anyone acts on. Overview still carries the window and run for the pages
// that genuinely date their numbers.
export function TopBar({ onSweep, sweeping, role, onRoleChange }: TopBarProps) {
  const title = titleFor(useLocation().pathname)

  return (
    <header className="top-bar">
      <div className="top-bar__heading">
        <h1 className="top-bar__title">{title ?? 'Signal Desk'}</h1>
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
