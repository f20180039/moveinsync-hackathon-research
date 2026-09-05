import { render, screen } from '@testing-library/react'
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
})
