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

// The MoveInSync-style left sidebar. Collapses to icons only below 1024px
// (pure CSS -- the labels stay in the DOM, hidden, so a screen reader still
// gets the full accessible name via the link, not an icon-only glyph).
export function Sidebar({ alertCount }: { alertCount: number }) {
  return (
    <nav aria-label="Primary" className="sidebar">
      <div className="sidebar__brand">
        <span aria-hidden="true">◆</span>
        <span className="sidebar__brand-name">Signal Desk</span>
      </div>

      <ul className="sidebar__section">
        {MAIN_ITEMS.map((item) => (
          <li key={item.to}>
            <NavLink to={item.to} end={item.end} className={linkClassName}>
              <span className="sidebar__icon" aria-hidden="true">
                {item.icon}
              </span>
              <span className="sidebar__label">{item.label}</span>
              {item.to === '/alerts' && alertCount > 0 && (
                <span className="sidebar__badge">{alertCount}</span>
              )}
            </NavLink>
          </li>
        ))}
      </ul>

      <div className="sidebar__section-label">Reports</div>
      <ul className="sidebar__section">
        {REPORT_ITEMS.map((item) => (
          <li key={item.to}>
            <NavLink to={item.to} end={item.end} className={linkClassName}>
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
