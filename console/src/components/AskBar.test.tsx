import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AskBar } from './AskBar.tsx'

function notFound() {
  return Promise.resolve({ ok: false, status: 404, statusText: 'Not Found', text: async () => '' } as Response)
}

function jsonResponse(body: unknown) {
  return Promise.resolve({ ok: true, json: async () => body } as Response)
}

function healthResponse(capabilities?: string[]) {
  return jsonResponse({
    status: 'ok',
    activeMetrics: ['ota'],
    clock: '2026-09-05T09:00:00Z',
    ...(capabilities !== undefined && { capabilities }),
  })
}

function stubFetch(routes: { health?: () => Promise<Response>; ask?: () => Promise<Response> }) {
  const fetchMock = vi.fn((input: RequestInfo | URL) => {
    const url = String(input)
    if (url.includes('/api/health')) return routes.health?.() ?? notFound()
    if (url.includes('/api/ask')) return routes.ask?.() ?? notFound()
    return notFound()
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('AskBar', () => {
  it('disables the input when /api/health advertises capabilities without "ask"', async () => {
    stubFetch({ health: () => healthResponse(['decompose']) })

    render(<AskBar runId="run-1" />)

    expect(await screen.findByText('Interrogation lands with the tools — coming')).toBeInTheDocument()
    expect(screen.getByLabelText(/ask a question/i)).toBeDisabled()
  })

  it('stays available when /api/health omits `capabilities`, and a 422 does not disable it', async () => {
    stubFetch({
      health: () => healthResponse(undefined),
      ask: () => Promise.resolve({ ok: false, status: 422, statusText: 'Unprocessable Entity', text: async () => '' } as Response),
    })

    const user = userEvent.setup()
    render(<AskBar runId="run-1" />)

    const input = await screen.findByLabelText(/ask a question/i)
    await waitFor(() => expect(input).toBeEnabled())

    await user.type(input, 'a rejected question')
    await user.click(screen.getByRole('button', { name: /^send$/i }))

    expect(await screen.findByText(/could not reach the assistant/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/ask a question/i)).toBeEnabled()
  })

  it('shows the four suggested question chips', () => {
    vi.stubGlobal('fetch', vi.fn(() => notFound()))

    render(<AskBar runId="run-1" />)

    expect(screen.getByRole('button', { name: 'Why is OTA low this week?' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Which vendor is underperforming?' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Where are no-shows concentrated?' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'What changed vs last week?' })).toBeInTheDocument()
  })

  it('posts a question and renders the answer plus a collapsible trace, when /api/ask exists', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/api/ask')) {
        return jsonResponse({ answer: 'Vendor A and Vendor C are dragging OTA down.', trace: ['step 1', 'step 2'] })
      }
      return notFound()
    })
    vi.stubGlobal('fetch', fetchMock)

    const user = userEvent.setup()
    render(<AskBar runId="run-1" />)

    await screen.findByLabelText(/ask a question/i)
    await user.click(screen.getByRole('button', { name: 'Why is OTA low this week?' }))

    expect(await screen.findByText('Vendor A and Vendor C are dragging OTA down.')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /show trace/i }))
    expect(screen.getByText(/step 1/)).toBeInTheDocument()
  })
})
