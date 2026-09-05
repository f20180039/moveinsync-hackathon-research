import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import fixture from '../../handoff/fake-findings.json'
import App from './App.tsx'

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
    if (url.includes('/api/runs/latest/findings')) {
      return jsonResponse({
        runId: fixture.runId,
        windowLabel: fixture.windowLabel,
        findings: fixture.findings,
      })
    }
    if (url.includes('/api/health/feeds')) {
      return jsonResponse(fixture.feedHealth)
    }
    if (url.includes('/api/cost')) {
      return jsonResponse(fixture.cost)
    }
    if (url.includes('/api/dispatch/log')) {
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
      return jsonResponse({ runId: fixture.runId, dispatched: [] })
    }
    return jsonResponse({})
  })
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
})

describe('App', () => {
  it('loads and renders the header, feed health and findings from the API', async () => {
    vi.stubGlobal('fetch', mockFetchForRoutes())

    renderApp()

    expect(await screen.findByText('Signal Desk')).toBeInTheDocument()
    expect(await screen.findByText(new RegExp(fixture.runId))).toBeInTheDocument()
    expect(await screen.findByText(fixture.findings[0].metricLabel)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /sweep now/i })).toBeInTheDocument()
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
    // together, then the first rejection short-circuits the rest).
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(fetchMock.mock.calls.length).toBeLessThanOrEqual(3)
  })

  it('fetches each route exactly once on initial render, with no polling', async () => {
    const fetchMock = mockFetchForRoutes()
    vi.stubGlobal('fetch', fetchMock)

    renderApp()

    expect(await screen.findByText('Signal Desk')).toBeInTheDocument()
    await screen.findByText(fixture.findings[0].metricLabel)

    // Give any stray timer/poll a chance to fire before asserting call counts.
    await new Promise((resolve) => setTimeout(resolve, 100))

    const callsFor = (path: string) =>
      fetchMock.mock.calls.filter(([input]) => String(input).includes(path)).length

    expect(callsFor('/api/runs/latest/findings')).toBe(1)
    expect(callsFor('/api/health/feeds')).toBe(1)
    expect(callsFor('/api/cost')).toBe(1)
  })

  it('places the summary strip before the findings list on the Findings page', async () => {
    vi.stubGlobal('fetch', mockFetchForRoutes())

    const { container } = renderApp()

    await screen.findByText(fixture.findings[0].metricLabel)

    const summaryStrip = container.querySelector('[data-testid="summary-strip"]')
    const findingsSection = container.querySelector('[data-testid="findings-section"]')
    expect(summaryStrip).toBeInTheDocument()
    expect(findingsSection).toBeInTheDocument()

    const position = summaryStrip!.compareDocumentPosition(findingsSection!)
    expect(position & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('has a Primary nav with the four route links', async () => {
    vi.stubGlobal('fetch', mockFetchForRoutes())

    renderApp()
    await screen.findByText(fixture.findings[0].metricLabel)

    const nav = screen.getByRole('navigation', { name: /primary/i })
    expect(nav).toHaveTextContent('Findings')
    expect(nav).toHaveTextContent('Brief')
    expect(nav).toHaveTextContent('Feed health')
    expect(nav).toHaveTextContent('Cost')
  })

  it.each([
    ['/', /findings/i],
    ['/brief', /brief/i],
    ['/health', /feed health/i],
    ['/cost', /cost/i],
  ])('renders the page heading for %s', async (path, expectedHeading) => {
    vi.stubGlobal('fetch', mockFetchForRoutes())

    renderApp([path])
    await screen.findByText(fixture.findings[0].metricLabel).catch(() => {
      // Only the Findings page renders a finding's metric label -- other
      // routes just need the fetches to settle before asserting.
    })
    await new Promise((resolve) => setTimeout(resolve, 20))

    expect(screen.getByRole('heading', { level: 1, name: expectedHeading })).toBeInTheDocument()
  })

  it('renders every control as the shared Button component (the row toggle is a deliberate exception)', async () => {
    const fetchMock = mockFetchForRoutes()
    vi.stubGlobal('fetch', fetchMock)

    const user = userEvent.setup()
    const { container } = renderApp()

    await screen.findByText(fixture.findings[0].metricLabel)

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

  it('never renders a raw enum value as text on the Findings page (every row expanded)', async () => {
    vi.stubGlobal('fetch', mockFetchForRoutes())

    const user = userEvent.setup()
    const { container } = renderApp(['/'])

    await screen.findByText(fixture.findings[0].metricLabel)

    // Expand every finding row so evidence panels (audiences, cause) render.
    for (const toggle of container.querySelectorAll<HTMLElement>('.finding-row__toggle')) {
      await user.click(toggle)
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

  it('never renders a raw enum value as text on the Feed health page', async () => {
    vi.stubGlobal('fetch', mockFetchForRoutes())

    const { container } = renderApp(['/health'])

    await screen.findByRole('heading', { level: 1, name: /feed health/i })

    expectNoRawEnumText(container)
  })

  it('never renders a raw enum value as text on the Cost page', async () => {
    vi.stubGlobal('fetch', mockFetchForRoutes())

    const { container } = renderApp(['/cost'])

    await screen.findByRole('heading', { level: 1, name: /cost/i })

    expectNoRawEnumText(container)
  })
})
