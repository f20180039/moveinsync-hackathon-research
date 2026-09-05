import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import fixture from '../../handoff/fake-findings.json'
import type { EmployeeImpact } from './api/types.ts'
import App from './App.tsx'
import { useAppStore } from './store.ts'

function jsonResponse(body: unknown) {
  return Promise.resolve({ ok: true, json: async () => body } as Response)
}

function notFound() {
  return Promise.resolve({ ok: false, status: 404, statusText: 'Not Found', text: async () => '' } as Response)
}

// Raw underscore-separated enums (BELOW_TARGET, TRANSPORT_MANAGER, ...).
const RAW_UNDERSCORE_ENUM = /[A-Z]+_[A-Z_]+/
// Bare all-uppercase words of 3+ letters (BUS, LOGIN, EARLY, ...) -- catches
// an enum-like code that has no underscore to trip the pattern above.
// Legitimate acronyms are whitelisted explicitly rather than excluded by
// pattern, so a new one has to be a deliberate, reviewable addition.
const BARE_UPPERCASE_WORD = /\b[A-Z]{3,}\b/g
const ACRONYM_WHITELIST = new Set(['SQL', 'INR', 'OTA', 'OTD', 'SLA', 'API'])

// The evidence SQL block is raw SQL, deliberately verbatim and "runnable
// as-is" -- it is expected to contain SELECT/FROM/WHERE/CASE/... and quoted
// literal values like 'LOGIN' or 'BUS'. That is not an enum leaking into a
// UI label; it is literal query text the panel promises never to alter, so
// it is excluded from both scans below.
const SQL_BLOCK_SELECTOR = '.evidence-panel__sql-block'

function collectOffendingText(container: HTMLElement, pattern: RegExp, whitelist?: Set<string>): string[] {
  const globalPattern = new RegExp(pattern.source, pattern.flags.includes('g') ? pattern.flags : `${pattern.flags}g`)
  const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT)
  const offenders: string[] = []
  let node = walker.nextNode()
  while (node) {
    const text = node.textContent
    const insideSql = node.parentElement?.closest(SQL_BLOCK_SELECTOR) != null
    if (text && !insideSql) {
      for (const match of text.match(globalPattern) ?? []) {
        if (!whitelist?.has(match)) offenders.push(match)
      }
    }
    node = walker.nextNode()
  }
  return offenders
}

function expectNoRawEnumText(container: HTMLElement) {
  expect(collectOffendingText(container, RAW_UNDERSCORE_ENUM)).toEqual([])
  expect(collectOffendingText(container, BARE_UPPERCASE_WORD, ACRONYM_WHITELIST)).toEqual([])
}

function mockFetchForRoutes() {
  return vi.fn((input: RequestInfo | URL) => {
    const url = String(input)
    if (url.includes('/api/sweep')) {
      return jsonResponse({ runId: fixture.runId, findingCount: fixture.findings.length })
    }
    // Both /latest (most of the app) and the per-run endpoint (Review
    // reports, which fetch the run the sweep above just returned rather
    // than /latest) resolve to the same fixture here.
    if (url.includes('/api/runs/latest/findings') || url.includes(`/api/runs/${fixture.runId}/findings`)) {
      return jsonResponse({
        runId: fixture.runId,
        windowLabel: fixture.windowLabel,
        findings: fixture.findings,
      })
    }
    if (url.includes('/api/health/feeds')) {
      return jsonResponse(fixture.feedHealth)
    }
    // GET /api/health -- the capability list every optional-endpoint
    // consumer feature-detects from. "ask" is deliberately absent: the
    // routes below still 404 /api/ask, and the two must agree.
    if (url.includes('/api/health')) {
      return jsonResponse({
        status: 'ok',
        activeMetrics: ['ota'],
        clock: fixture.windowLabel,
        capabilities: ['employees'],
      })
    }
    if (url.includes('/api/employees/impact')) {
      return jsonResponse(employeeImpact)
    }
    if (url.includes('/api/cost')) {
      return jsonResponse(fixture.cost)
    }
    if (url.includes('/api/dispatch/log')) {
      return notFound()
    }
    if (url.includes('/decompose') || url.includes('/api/ask') || url.includes('/safety')) {
      // None of these are live yet in reality -- matches
      // decomposeFinding()/ask()/getSafety()'s real-world 404, so every
      // caller's graceful-absence path is what actually runs in these
      // tests, not an accidental `{}` success.
      return notFound()
    }
    if (url.includes('/brief')) {
      return jsonResponse({
        runId: fixture.runId,
        audience: 'TRANSPORT_MANAGER',
        brief: 'Sample brief text.',
        source: 'template',
      })
    }
    if (url.includes('/api/dispatch/')) {
      // A populated result (not an empty array) so the enum guard, when
      // it clicks Dispatch on a Review report, actually exercises
      // label('audience', ...) / label('channel', ...) on real values
      // instead of vacuously passing over an empty list.
      return jsonResponse({
        runId: fixture.runId,
        dispatched: [
          {
            audience: 'TRANSPORT_MANAGER',
            tier: 'BREACH',
            channels: [{ channel: 'slack', delivered: true, detail: '' }],
            findingIds: [],
          },
        ],
      })
    }
    return jsonResponse({})
  })
}

// Shapes match service/signaldesk/api.py's get_employees_impact(). Values
// are deliberately non-zero so the enum guard and the heading check scan
// real rendered rows rather than an empty page.
const employeeImpact: EmployeeImpact = {
  runId: fixture.runId,
  window: { start: 0, end: 1, label: fixture.windowLabel },
  employeesImpacted: 1204,
  ridersInWindow: 8110,
  noShowLegs: 317,
  latePickupLegs: 2489,
  avgPickupDelayMin: 12.4,
  medianPickupDelayMin: 7.5,
  employeeCausedDelayShare: 0.0812,
  byShiftBand: [{ shiftBand: 'NIGHT', legs: 4120, noShows: 190, latePickups: 1310, impacted: 622 }],
  bySite: [{ site: 'Santa Clara Office', legs: 5200, noShows: 210, latePickups: 1502, impacted: 781 }],
  byVendor: [{ vendor: 'Rohan Mikhailov Travel', legs: 3980, noShows: 175, latePickups: 1204, impacted: 604 }],
  costPerRider: 214.6,
  costPerRiderTrend: 198.2,
}

// The top bar no longer prints the run id (it is a page title now, and
// only that), so "the initial load has finished" is signalled by the
// content region itself: <main> renders only once loading is done and no
// error is set.
function findLoaded() {
  return screen.findByRole('main')
}

function renderApp(initialEntries: string[] = ['/']) {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <App />
    </MemoryRouter>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
  // useAppStore is a module-level singleton (zustand + persist) --
  // without this, a role change in one test would leak into every test
  // that runs after it in this file.
  useAppStore.setState({ role: 'TRANSPORT_MANAGER' })
  window.localStorage.clear()
})

describe('App', () => {
  it('loads and renders the shell (top bar, sidebar) from the API', async () => {
    vi.stubGlobal('fetch', mockFetchForRoutes())

    renderApp()

    expect(await findLoaded()).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /sweep now/i })).toBeInTheDocument()
    expect(screen.getByRole('navigation', { name: /primary/i })).toBeInTheDocument()
  })

  it('shell: only the main region scrolls -- structural check (jsdom does not apply our stylesheet, so this checks class names, not computed CSS)', async () => {
    vi.stubGlobal('fetch', mockFetchForRoutes())

    const { container } = renderApp()
    await findLoaded()

    // These class names are exactly what App.css's sticky-shell rules key
    // off (`.shell__main { overflow-y: auto; ... }`, `.sidebar { position:
    // sticky; ... }`) -- confirmed structurally here; confirmed visually
    // by eye at 1440x900 and 390px (see the Stage 4 report).
    const shell = container.querySelector('.shell')
    const sidebar = container.querySelector('.sidebar')
    const main = container.querySelector('.shell__main')
    expect(shell).toBeInTheDocument()
    expect(sidebar).toBeInTheDocument()
    expect(main).toBeInTheDocument()

    // The sidebar is one persistent element, not remounted per route --
    // the same DOM node survives a route change (a weak but real proxy for
    // "the sidebar has its own stable scroll region, independent of the
    // page content changing underneath it").
    await userEvent.setup().click(screen.getByRole('link', { name: 'Insights' }))
    await screen.findByRole('heading', { level: 1, name: /insights/i })
    expect(container.querySelector('.sidebar')).toBe(sidebar)
  })

  it('shows the error message, not a stack, when a fetch fails', async () => {
    const fetchMock = vi.fn(() =>
      Promise.resolve({ ok: false, status: 500, statusText: 'Server Error', text: async () => '' } as Response),
    )
    vi.stubGlobal('fetch', fetchMock)

    renderApp()

    expect(await screen.findByText(/500 Server Error/)).toBeInTheDocument()

    // No auto-retry: a failed initial load must not keep hammering the API.
    // Each of the three routes is called once (Promise.all fires them
    // together, then the first rejection short-circuits the rest), plus the
    // assistant footer's one capabilities read -- it is mounted on every
    // page, including this one.
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(fetchMock.mock.calls.length).toBeLessThanOrEqual(4)
  })

  it('fetches each route exactly once on initial render, with no polling', async () => {
    const fetchMock = mockFetchForRoutes()
    vi.stubGlobal('fetch', fetchMock)

    renderApp(['/findings'])

    expect(await findLoaded()).toBeInTheDocument()
    await screen.findAllByText(fixture.findings[0].metricLabel)

    // Give any stray timer/poll a chance to fire before asserting call counts.
    await new Promise((resolve) => setTimeout(resolve, 100))

    const callsFor = (path: string) =>
      fetchMock.mock.calls.filter(([input]) => String(input).includes(path)).length

    expect(callsFor('/api/runs/latest/findings')).toBe(1)
    expect(callsFor('/api/health/feeds')).toBe(1)
    expect(callsFor('/api/cost')).toBe(1)
  })

  it('has a Primary sidebar nav with every section link', async () => {
    vi.stubGlobal('fetch', mockFetchForRoutes())

    renderApp()
    await findLoaded()

    const nav = screen.getByRole('navigation', { name: /primary/i })
    expect(nav).toHaveTextContent('Overview')
    expect(nav).toHaveTextContent('Alerts')
    expect(nav).toHaveTextContent('Insights')
    expect(nav).toHaveTextContent('Employees')
    expect(nav).toHaveTextContent('Vendors')
    expect(nav).toHaveTextContent('Data health')
    expect(nav).toHaveTextContent('Weekly review')
    expect(nav).toHaveTextContent('Monthly review')

    // /cost and /brief are routed but not linked (nav.ts) -- they are
    // reached from the page that needs them, not from the daily nav. The
    // assistant has no slot either: it is the sticky footer on every page.
    expect(nav).not.toHaveTextContent('Brief & dispatch')
    expect(nav).not.toHaveTextContent('Ask')
  })

  it('shows an unread-alert badge counting CONCERN/BREACH findings', async () => {
    vi.stubGlobal('fetch', mockFetchForRoutes())

    renderApp()
    await findLoaded()

    const expectedCount = fixture.findings.filter((f) => f.tier === 'CONCERN' || f.tier === 'BREACH').length
    const nav = screen.getByRole('navigation', { name: /primary/i })
    expect(nav).toHaveTextContent(String(expectedCount))
  })

  it.each([
    ['/', /overview/i],
    ['/alerts', /alerts/i],
    ['/findings', /insights/i],
    ['/employees', /employees/i],
    ['/vendors', /vendors/i],
    ['/health', /data health/i],
    ['/cost', /cost/i],
    ['/reports/weekly', /weekly review/i],
    ['/reports/monthly', /monthly review/i],
    ['/brief', /brief/i],
  ])('renders the page heading for %s', async (path, expectedHeading) => {
    vi.stubGlobal('fetch', mockFetchForRoutes())

    renderApp([path])
    await findLoaded()
    await new Promise((resolve) => setTimeout(resolve, 20))

    expect(screen.getByRole('heading', { level: 1, name: expectedHeading })).toBeInTheDocument()
  })

  it('renders every control as the shared Button component (the row toggle is a deliberate exception)', async () => {
    const fetchMock = mockFetchForRoutes()
    vi.stubGlobal('fetch', fetchMock)

    const user = userEvent.setup()
    const { container } = renderApp(['/findings'])

    await screen.findAllByText(fixture.findings[0].metricLabel)

    // Expand a finding row so its "Copy SQL" button renders too.
    const rowToggle = container.querySelector('.finding-row__toggle') as HTMLElement
    await user.click(rowToggle)

    const buttons = container.querySelectorAll('button')
    expect(buttons.length).toBeGreaterThan(1)
    for (const button of buttons) {
      // Every button, without exception, carries the shared reset class.
      expect(button.classList.contains('btn')).toBe(true)

      if (button.classList.contains('finding-row__toggle')) {
        // Every ranked-list row toggle deliberately isn't a `Button`
        // instance -- a full-width table row can't be a pill-shaped
        // fixed-height control -- so all of them are exempted from the
        // identity check (there are 8 finding rows, only one expanded).
        expect(button.dataset.component).toBeUndefined()
      } else {
        expect(button.dataset.component).toBe('Button')
      }
    }
  })

  it.each([
    ['/'],
    ['/alerts'],
    ['/findings'],
    ['/employees'],
    ['/vendors'],
    ['/health'],
    ['/cost'],
    ['/reports/weekly'],
    ['/reports/monthly'],
  ])('never renders a raw enum value as text on %s', async (path) => {
    vi.stubGlobal('fetch', mockFetchForRoutes())

    const user = userEvent.setup()
    const { container } = renderApp([path])

    await findLoaded()
    await new Promise((resolve) => setTimeout(resolve, 20))

    // Expand every finding row (Insights/Alerts/Vendors may have some) so
    // evidence panels (audiences, cause) render too.
    for (const toggle of container.querySelectorAll<HTMLElement>('.finding-row__toggle')) {
      await user.click(toggle)
    }

    // On Overview, also open one priority card's Investigate so its
    // decomposition table and VENDOR/SITE/SHIFT/DELAY_REASON dim selector
    // get scanned too, not just the collapsed card.
    const investigateButtons = screen.queryAllByRole('button', { name: /investigate/i })
    if (investigateButtons.length > 0) {
      await user.click(investigateButtons[0])
    }

    // The two report routes render nothing worth scanning until a review
    // is run (KPI row, audience select and dispatch results all live
    // inside `{run && ...}`) -- without this, this test only ever
    // scanned an empty page and could never have caught an enum leaking
    // into any of that content.
    const runReviewButton = screen.queryByRole('button', { name: /run (week|month) review/i })
    if (runReviewButton) {
      await user.click(runReviewButton)
      // Not findByText(windowLabel) -- Overview's own header carries the
      // same window text, so it is ambiguous once a KPI row has
      // rendered. The Dispatch button only exists once `run` is set, so
      // waiting for it is an unambiguous signal that the review's own
      // content is up.
      await screen.findByRole('button', { name: /dispatch/i })
      await user.click(screen.getByRole('button', { name: /dispatch/i }))
      // Substring match -- the rendered <li> is "Slack · delivered" in
      // one text node, not "Slack" alone.
      await screen.findByText(/slack/i)
    }

    expectNoRawEnumText(container)
  })

  it('never renders a raw enum value as text on the Brief page (brief fetched)', async () => {
    vi.stubGlobal('fetch', mockFetchForRoutes())

    const user = userEvent.setup()
    const { container } = renderApp(['/brief'])

    await screen.findByRole('heading', { level: 1, name: /brief/i })
    await user.click(screen.getByRole('button', { name: /preview brief/i }))
    await screen.findByText('Sample brief text.')

    expectNoRawEnumText(container)
  })
})

describe('App: role switch', () => {
  it('switching to Facilities head narrows the sidebar nav and changes the KPI set', async () => {
    vi.stubGlobal('fetch', mockFetchForRoutes())
    const user = userEvent.setup()
    const { container } = renderApp()
    const kpiRow = () => container.querySelector('.kpi-row') as HTMLElement

    await findLoaded()
    expect(screen.getByRole('link', { name: 'Insights' })).toBeInTheDocument()
    expect(within(kpiRow()).getByText('On-time arrival')).toBeInTheDocument() // Transport manager's KPI row

    await user.selectOptions(screen.getByLabelText(/viewing as/i), 'FACILITIES_HEAD')

    // Insights and Data health are Transport manager's tools, not
    // Facilities head's.
    expect(screen.queryByRole('link', { name: 'Insights' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Data health' })).not.toBeInTheDocument()
    // Employee-level triage is not this role's job either -- it acts on
    // Breach-level cost/safety/contract questions.
    expect(screen.queryByRole('link', { name: 'Employees' })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Vendors' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Weekly review' })).toBeInTheDocument()

    // Facilities head's own KPI set, with its strip label.
    expect(screen.getByText('Cost · Safety · Experience')).toBeInTheDocument()
    expect(within(kpiRow()).getByText('Cost per rider')).toBeInTheDocument()
    expect(within(kpiRow()).queryByText('On-time departure')).not.toBeInTheDocument()
  })

  it('a route hidden from the current role\'s nav still renders when navigated to directly (no 403)', async () => {
    vi.stubGlobal('fetch', mockFetchForRoutes())
    const user = userEvent.setup()
    renderApp()

    await findLoaded()
    await user.selectOptions(screen.getByLabelText(/viewing as/i), 'FACILITIES_HEAD')
    expect(screen.queryByRole('link', { name: 'Insights' })).not.toBeInTheDocument()

    // /findings is not linked for this role, but App.tsx's route table
    // never changes -- a direct visit still renders the page in full.
    renderApp(['/findings'])
    await screen.findByRole('heading', { level: 1, name: /insights/i })
    expect(await screen.findAllByText(fixture.findings[0].metricLabel)).not.toHaveLength(0)
  })

  it('the role choice persists (zustand + localStorage) across a remount', async () => {
    vi.stubGlobal('fetch', mockFetchForRoutes())
    const user = userEvent.setup()
    const { unmount } = renderApp()

    await findLoaded()
    await user.selectOptions(screen.getByLabelText(/viewing as/i), 'FACILITIES_HEAD')
    expect(screen.getByLabelText(/viewing as/i)).toHaveValue('FACILITIES_HEAD')

    unmount()

    renderApp()
    await findLoaded()
    expect(screen.getByLabelText(/viewing as/i)).toHaveValue('FACILITIES_HEAD')
  })

  it('the assistant conversation survives a role switch (it is mounted once, independent of role)', async () => {
    vi.stubGlobal('fetch', mockFetchForRoutes())
    const user = userEvent.setup()
    renderApp()

    await findLoaded()
    await user.click(screen.getByRole('button', { name: /expand/i }))
    await screen.findByRole('region', { name: /mobility intelligence assistant/i })

    await user.selectOptions(screen.getByLabelText(/viewing as/i), 'FACILITIES_HEAD')

    // Still expanded, still the same conversation -- switching role didn't
    // remount (and so didn't collapse) the assistant.
    expect(screen.getByRole('region', { name: /mobility intelligence assistant/i })).toBeInTheDocument()
  })
})
