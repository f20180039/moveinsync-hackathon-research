import { NavLink } from 'react-router-dom'

interface NavItem {
  to: string
  label: string
  icon: string
  end?: boolean
}

const MAIN_ITEMS: NavItem[] = [
  { to: '/', label: 'Overview', icon: '◧', end: true },
  { to: '/alerts', label: 'Alerts', icon: '⚠' },
  { to: '/findings', label: 'Insights', icon: '☰' },
  { to: '/vendors', label: 'Vendors', icon: '🚌' },
  { to: '/health', label: 'Data health', icon: '🩺' },
  { to: '/cost', label: 'Cost', icon: '₹' },
]

const REPORT_ITEMS: NavItem[] = [
  { to: '/reports/weekly', label: 'Weekly review', icon: '📅' },
  { to: '/reports/monthly', label: 'Monthly review', icon: '🗓' },
  { to: '/brief', label: 'Brief & dispatch', icon: '✉' },
]

function linkClassName({ isActive }: { isActive: boolean }): string {
  return `sidebar__link${isActive ? ' sidebar__link--active' : ''}`
}

export type AlertSeverity = 'breach' | 'concern' | null

export interface SidebarProps {
  alertCount: number
  // Red only when a Breach exists among the alerts, amber when the worst
  // is a Concern, no badge at all when there are none -- one more place
  // severity is legible before reading a single word.
  alertSeverity: AlertSeverity
  // The current role's visible nav paths (roles.ts) -- a path not in this
  // set is simply not linked here; App.tsx's route table is unchanged, so
  // a direct link to a hidden page still renders normally (no 403).
  // Optional so every existing caller/test keeps showing every link.
  visibleNavPaths?: Set<string>
}

// The MoveInSync-style left sidebar. Collapses to icons only below 1024px
// (pure CSS -- the labels stay in the DOM, visually hidden rather than
// display:none, so a screen reader still gets the full accessible name via
// the link, not an icon-only glyph). `aria-label` is belt-and-braces on top
// of that CSS technique: it fixes the accessible name to exactly the nav
// item's label regardless of viewport width or how the label is styled.
export function Sidebar({ alertCount, alertSeverity, visibleNavPaths }: SidebarProps) {
  const isVisible = (path: string) => !visibleNavPaths || visibleNavPaths.has(path)
  const mainItems = MAIN_ITEMS.filter((item) => isVisible(item.to))
  const reportItems = REPORT_ITEMS.filter((item) => isVisible(item.to))

  return (
    <nav aria-label="Primary" className="sidebar">
      <div className="sidebar__brand">
        <span aria-hidden="true">◆</span>
        <span className="sidebar__brand-name">Signal Desk</span>
      </div>

      <ul className="sidebar__section">
        {mainItems.map((item) => (
          <li key={item.to}>
            <NavLink to={item.to} end={item.end} className={linkClassName} aria-label={item.label}>
              <span className="sidebar__icon" aria-hidden="true">
                {item.icon}
              </span>
              <span className="sidebar__label">{item.label}</span>
              {item.to === '/alerts' && alertCount > 0 && (
                <span className={`sidebar__badge sidebar__badge--${alertSeverity}`}>{alertCount}</span>
              )}
            </NavLink>
          </li>
        ))}
      </ul>

      <div className="sidebar__section-label">Reports</div>
      <ul className="sidebar__section">
        {reportItems.map((item) => (
          <li key={item.to}>
            <NavLink to={item.to} end={item.end} className={linkClassName} aria-label={item.label}>
              <span className="sidebar__icon" aria-hidden="true">
                {item.icon}
              </span>
              <span className="sidebar__label">{item.label}</span>
            </NavLink>
          </li>
        ))}
      </ul>

      <p className="sidebar__tagline">Senses, reasons and acts -- not just a dashboard.</p>
    </nav>
  )
}
