import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import fixture from '../../handoff/fake-findings.json'
import App from './App.tsx'

function jsonResponse(body: unknown) {
  return Promise.resolve({ ok: true, json: async () => body } as Response)
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

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('App', () => {
  it('loads and renders the header, feed health and findings from the API', async () => {
    vi.stubGlobal('fetch', mockFetchForRoutes())

    render(<App />)

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

    render(<App />)

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

    render(<App />)

    expect(await screen.findByText('Signal Desk')).toBeInTheDocument()
    await screen.findByText(fixture.findings[0].metricLabel)

    // Give any stray timer/poll a chance to fire before asserting call counts.
    await new Promise((resolve) => setTimeout(resolve, 100))

    const callsFor = (path: string) =>
      fetchMock.mock.calls.filter(([input]) => String(input).includes(path)).length

    expect(callsFor('/api/runs/latest/findings')).toBe(1)
    expect(callsFor('/api/health/feeds')).toBe(1)
    expect(callsFor('/api/cost')).toBe(1)
    expect(fetchMock).toHaveBeenCalledTimes(3)
  })

  it('places the control strip before the findings list in DOM order', async () => {
    vi.stubGlobal('fetch', mockFetchForRoutes())

    const { container } = render(<App />)

    await screen.findByText(fixture.findings[0].metricLabel)

    const controlStrip = container.querySelector('[data-testid="control-strip"]')
    const findingsSection = container.querySelector('[data-testid="findings-section"]')
    expect(controlStrip).toBeInTheDocument()
    expect(findingsSection).toBeInTheDocument()

    const position = controlStrip!.compareDocumentPosition(findingsSection!)
    expect(position & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('renders every button as the shared Button component', async () => {
    const fetchMock = mockFetchForRoutes()
    vi.stubGlobal('fetch', fetchMock)

    const user = userEvent.setup()
    const { container } = render(<App />)

    await screen.findByText(fixture.findings[0].metricLabel)

    // Expand a finding row so its "Copy SQL" button renders too.
    const rowToggle = container.querySelector('.finding-row__toggle') as HTMLElement
    await user.click(rowToggle)

    // Fetch a brief so its "show/hide brief" toggle renders too.
    await user.click(screen.getByRole('button', { name: /preview brief/i }))
    await screen.findByText(/source: template/)

    // Dispatch it so nothing is left unrendered.
    await user.click(screen.getByRole('button', { name: /dispatch/i }))
    await screen.findByRole('button', { name: /hide brief/i })

    const buttons = container.querySelectorAll('button')
    expect(buttons.length).toBeGreaterThan(0)
    for (const button of buttons) {
      expect(button.classList.contains('btn')).toBe(true)
    }
  })
})
