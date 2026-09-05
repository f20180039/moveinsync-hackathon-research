// The nav is defined ONCE, here. The sidebar renders it and the top bar
// resolves the current page's title from it, so the heading above a page can
// never drift from the link that got you there.

export interface NavItem {
  to: string
  label: string
  icon: string
  end?: boolean
}

export const MAIN_ITEMS: NavItem[] = [
  { to: '/', label: 'Overview', icon: '◧', end: true },
  { to: '/alerts', label: 'Alerts', icon: '⚠' },
  { to: '/findings', label: 'Insights', icon: '☰' },
  { to: '/employees', label: 'Employees', icon: '👥' },
  { to: '/vendors', label: 'Vendors', icon: '🚌' },
  { to: '/health', label: 'Data health', icon: '🩺' },
  { to: '/cost', label: 'Cost', icon: '₹' },
]

export const REPORT_ITEMS: NavItem[] = [
  { to: '/reports/weekly', label: 'Weekly review', icon: '📅' },
  { to: '/reports/monthly', label: 'Monthly review', icon: '🗓' },
  { to: '/brief', label: 'Brief & dispatch', icon: '✉' },
]

const ALL_ITEMS = [...MAIN_ITEMS, ...REPORT_ITEMS]

// Longest matching prefix wins, so a future nested route (/vendors/ABC)
// still resolves to "Vendors" rather than falling through. '/' is exact --
// it prefixes everything, so it can only match itself.
export function titleFor(pathname: string): string | null {
  if (pathname === '/') return 'Overview'
  const match = ALL_ITEMS.filter((item) => item.to !== '/')
    .filter((item) => pathname === item.to || pathname.startsWith(`${item.to}/`))
    .sort((a, b) => b.to.length - a.to.length)[0]
  return match?.label ?? null
}
