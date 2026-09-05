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

  it('never renders a raw SCREAMING_SNAKE_CASE enum value as text', async () => {
    vi.stubGlobal('fetch', mockFetchForRoutes())

    const user = userEvent.setup()
    const { container } = renderApp()

    await screen.findByText(fixture.findings[0].metricLabel)

    // Expand every finding row so evidence panels (audiences, cause) render.
    for (const toggle of container.querySelectorAll<HTMLElement>('.finding-row__toggle')) {
      await user.click(toggle)
    }

    const rawEnumPattern = /[A-Z]+_[A-Z_]+/
    const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT)
    const offenders: string[] = []
    let node = walker.nextNode()
    while (node) {
      if (node.textContent && rawEnumPattern.test(node.textContent)) {
        offenders.push(node.textContent)
      }
      node = walker.nextNode()
    }

    expect(offenders).toEqual([])
  })
})
