import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactElement } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AskResponse } from '../api/types.ts'
import { FloatingAssistant } from './FloatingAssistant.tsx'

// The panel's Expand control is a router link (it navigates to /chat), so
// every render needs a router around it -- the App shell mounts it inside
// one.
function renderPanel(ui: ReactElement) {
  return render(<MemoryRouter>{ui}</MemoryRouter>)
}

const STORAGE_KEY = 'signal-desk:assistant-conversation'

function notFound() {
  return Promise.resolve({ ok: false, status: 404, statusText: 'Not Found', text: async () => '' } as Response)
}

function jsonResponse(body: unknown) {
  return Promise.resolve({ ok: true, json: async () => body } as Response)
}

// A non-404 failure: the endpoint exists, this one request failed.
function errorResponse(status: number, statusText: string) {
  return Promise.resolve({ ok: false, status, statusText, text: async () => '' } as Response)
}

// GET /api/health with an explicit `capabilities` list. Pass undefined for
// an older service that predates the field entirely.
function healthResponse(capabilities?: string[]) {
  return jsonResponse({
    status: 'ok',
    activeMetrics: ['ota'],
    clock: '2026-09-05T09:00:00Z',
    ...(capabilities !== undefined && { capabilities }),
  })
}

// Routes the only two endpoints the assistant touches. Anything unrouted
// 404s, which for /api/health means "capabilities unknown".
function stubFetch(routes: { health?: () => Promise<Response>; ask?: () => Promise<Response> }) {
  // `init` is declared so a test can assert what was actually POSTed, not
  // merely that a POST happened.
  const fetchMock = vi.fn((input: RequestInfo | URL, _init?: RequestInit) => {
    const url = String(input)
    if (url.includes('/api/health')) return routes.health?.() ?? notFound()
    if (url.includes('/api/ask')) return routes.ask?.() ?? notFound()
    return notFound()
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function makeResponse(overrides: Partial<AskResponse> = {}): AskResponse {
  return {
    runId: 'run-1',
    question: 'Why is on-time low this week?',
    answer: 'Vendor A and Vendor C are dragging on-time down.',
    withheld: false,
    reason: null,
    trace: [{ tool: 'query_findings', arguments: { metric: 'ota' }, result: { rows: 2 } }],
    ...overrides,
  }
}

async function openPanel() {
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: /open mobility intelligence assistant/i }))
  return user
}

beforeEach(() => {
  window.localStorage.clear()
})

afterEach(() => {
  vi.unstubAllGlobals()
  window.localStorage.clear()
})

describe('FloatingAssistant', () => {
  it('renders a closed launcher by default -- no panel in the document', () => {
    vi.stubGlobal('fetch', vi.fn(() => notFound()))
    renderPanel(<FloatingAssistant runId="run-1" />)

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /open mobility intelligence assistant/i })).toBeInTheDocument()
  })

  it('opens a non-modal dialog panel on click', async () => {
    vi.stubGlobal('fetch', vi.fn(() => notFound()))
    renderPanel(<FloatingAssistant runId="run-1" />)

    await openPanel()

    const dialog = screen.getByRole('dialog', { name: /mobility intelligence assistant/i })
    expect(dialog).toHaveAttribute('aria-modal', 'false')
  })

  it('shows the four default suggested chips', async () => {
    vi.stubGlobal('fetch', vi.fn(() => notFound()))
    renderPanel(<FloatingAssistant runId="run-1" />)
    await openPanel()

    expect(screen.getByRole('button', { name: 'Why is on-time low this week?' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Which vendor is worst on on-time?' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Where are no-shows concentrated?' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Summarise this week' })).toBeInTheDocument()
  })

  it('lists the suggestions in their own column BEFORE the conversation', async () => {
    stubFetch({ health: () => healthResponse(['ask']) })
    const { container } = renderPanel(<FloatingAssistant runId="run-1" />)
    await openPanel()

    const body = container.querySelector('.assistant-panel__body') as HTMLElement
    const suggestions = body.querySelector('.assistant-panel__suggestions') as HTMLElement
    const conversation = body.querySelector('.assistant-panel__history') as HTMLElement

    // Both live inside the one row, suggestions first -- that DOM order is
    // what puts them on the left, and what the narrow-width media query
    // reflows to a row above the conversation rather than beside it.
    expect(suggestions).toBeInTheDocument()
    expect(conversation).toBeInTheDocument()
    expect(suggestions.compareDocumentPosition(conversation) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(within(suggestions).getByRole('button', { name: 'Why is on-time low this week?' })).toBeInTheDocument()
    expect(within(suggestions).getByRole('heading', { name: /suggested/i })).toBeInTheDocument()
    // The conversation column holds no starter buttons of its own.
    expect(within(conversation).queryByRole('button', { name: /why is on-time/i })).not.toBeInTheDocument()
  })

  it('clicking a suggestion in the left column asks exactly that question', async () => {
    const fetchMock = stubFetch({
      health: () => healthResponse(['ask']),
      ask: () => jsonResponse(makeResponse({ answer: 'Vendor C is worst on on-time.' })),
    })
    const { container } = renderPanel(<FloatingAssistant runId="run-1" />)
    const user = await openPanel()
    await screen.findByLabelText(/ask a question/i)

    const suggestions = container.querySelector('.assistant-panel__suggestions') as HTMLElement
    await user.click(within(suggestions).getByRole('button', { name: 'Which vendor is worst on on-time?' }))

    expect(await screen.findByText('Vendor C is worst on on-time.')).toBeInTheDocument()
    const askCall = fetchMock.mock.calls.find(([input]) => String(input).includes('/api/ask'))
    expect(JSON.parse(String(askCall?.[1]?.body))).toEqual({
      runId: 'run-1',
      question: 'Which vendor is worst on on-time?',
    })
  })

  it('accepts an override list of suggested questions (Stage 7 role-specific chips)', async () => {
    vi.stubGlobal('fetch', vi.fn(() => notFound()))
    renderPanel(<FloatingAssistant runId="run-1" suggestedQuestions={['Which vendors are recurring laggards?']} />)
    await openPanel()

    expect(screen.getByRole('button', { name: 'Which vendors are recurring laggards?' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Which vendor is worst on on-time?' })).not.toBeInTheDocument()
  })

  it('disables the input when /api/health advertises capabilities without "ask"', async () => {
    stubFetch({ health: () => healthResponse(['decompose', 'safety', 'employees']) })
    renderPanel(<FloatingAssistant runId="run-1" />)
    await openPanel()

    expect(await screen.findByText('Interrogation lands with the tools — coming')).toBeInTheDocument()
    expect(screen.getByLabelText(/ask a question/i)).toBeDisabled()
  })

  it('stays available when /api/health omits `capabilities` entirely (older service)', async () => {
    // Absence of evidence is not evidence of absence: a service that
    // predates the field still serves /api/ask.
    stubFetch({ health: () => healthResponse(undefined) })
    renderPanel(<FloatingAssistant runId="run-1" />)
    await openPanel()

    const input = await screen.findByLabelText(/ask a question/i)
    await waitFor(() => expect(input).toBeEnabled())
    expect(screen.queryByText('Interrogation lands with the tools — coming')).not.toBeInTheDocument()
  })

  it('stays available when `capabilities` lists "ask"', async () => {
    stubFetch({ health: () => healthResponse(['ask', 'decompose']) })
    renderPanel(<FloatingAssistant runId="run-1" />)
    await openPanel()

    const input = await screen.findByLabelText(/ask a question/i)
    await waitFor(() => expect(input).toBeEnabled())
  })

  it('never probes /api/ask to feature-detect -- no request is sent until a question is asked', async () => {
    const fetchMock = stubFetch({ health: () => healthResponse(['ask']) })
    renderPanel(<FloatingAssistant runId="run-1" />)
    await openPanel()
    await screen.findByLabelText(/ask a question/i)

    await waitFor(() => expect(fetchMock).toHaveBeenCalled())
    const askCalls = fetchMock.mock.calls.filter(([input]) => String(input).includes('/api/ask'))
    expect(askCalls).toHaveLength(0)
  })

  it('leaves the input ENABLED when /api/ask answers 422, and surfaces the failure on that question', async () => {
    // The regression this locks: a 422 is a rejected question, not a
    // missing endpoint. The console used to disable the whole assistant.
    stubFetch({
      health: () => healthResponse(['ask']),
      ask: () => errorResponse(422, 'Unprocessable Entity'),
    })
    renderPanel(<FloatingAssistant runId="run-1" />)
    const user = await openPanel()
    const input = await screen.findByLabelText(/ask a question/i)

    await user.type(input, 'a question the service rejects')
    await user.click(screen.getByRole('button', { name: /^send$/i }))

    expect(await screen.findByText(/could not reach the assistant/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/ask a question/i)).toBeEnabled()
    expect(screen.queryByText('Interrogation lands with the tools — coming')).not.toBeInTheDocument()
  })

  it('disables the assistant when /api/ask itself answers 404', async () => {
    stubFetch({ health: () => healthResponse(['ask']), ask: () => notFound() })
    renderPanel(<FloatingAssistant runId="run-1" />)
    const user = await openPanel()
    const input = await screen.findByLabelText(/ask a question/i)

    await user.type(input, 'a question to an endpoint that is gone')
    await user.click(screen.getByRole('button', { name: /^send$/i }))

    expect(await screen.findByText(/does not serve the assistant endpoint/i)).toBeInTheDocument()
    await waitFor(() => expect(screen.getByLabelText(/ask a question/i)).toBeDisabled())
  })

  it('recovers when the run the console loaded has aged out of the service', async () => {
    // The reported bug: the console holds the run id it fetched at startup,
    // the service sweeps on and drops it, and the resulting 404 -- which
    // names the missing RUN, not a missing route -- was reported as "this
    // build does not serve the assistant endpoint" and disabled the
    // assistant for the rest of the session.
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.includes('/api/health')) return healthResponse(['ask'])
      if (!url.includes('/api/ask')) return notFound()
      const body = JSON.parse(String(init?.body))
      if (body.runId === 'latest') return jsonResponse(makeResponse({ answer: 'On-time fell to 88%.' }))
      return Promise.resolve({
        ok: false,
        status: 404,
        statusText: 'Not Found',
        text: async () => JSON.stringify({ detail: { error: `no run '${body.runId}'` } }),
      } as Response)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderPanel(<FloatingAssistant runId="run-1785542400000-b0" />)
    const user = await openPanel()
    await screen.findByLabelText(/ask a question/i)

    await user.type(screen.getByLabelText(/ask a question/i), 'why did on-time fall?')
    await user.click(screen.getByRole('button', { name: /^send$/i }))

    expect(await screen.findByText('On-time fell to 88%.')).toBeInTheDocument()
    expect(screen.queryByText(/does not serve the assistant endpoint/i)).not.toBeInTheDocument()
    // Still usable: an aged-out run is a routine condition, not a build
    // without an assistant.
    expect(screen.getByLabelText(/ask a question/i)).toBeEnabled()
  })

  it('Escape closes the panel and returns focus to the launcher', async () => {
    vi.stubGlobal('fetch', vi.fn(() => notFound()))
    renderPanel(<FloatingAssistant runId="run-1" />)
    const user = await openPanel()

    expect(screen.getByRole('dialog')).toBeInTheDocument()

    await user.keyboard('{Escape}')

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /open mobility intelligence assistant/i })).toHaveFocus()
  })

  it('posts a question and renders the answer plus a collapsible trace', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/api/ask')) return jsonResponse(makeResponse())
      return notFound()
    })
    vi.stubGlobal('fetch', fetchMock)

    renderPanel(<FloatingAssistant runId="run-1" />)
    const user = await openPanel()

    await screen.findByLabelText(/ask a question/i)
    await user.click(screen.getByRole('button', { name: 'Why is on-time low this week?' }))

    expect(await screen.findByText('Vendor A and Vendor C are dragging on-time down.')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /show trace/i }))
    expect(screen.getByText(/query_findings/)).toBeInTheDocument()
  })

  it('renders a withheld answer as the reason and trace, not an error', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/api/ask')) {
        return jsonResponse(
          makeResponse({
            answer: null,
            withheld: true,
            reason: 'This question needs data outside this window’s findings.',
          }),
        )
      }
      return notFound()
    })
    vi.stubGlobal('fetch', fetchMock)

    renderPanel(<FloatingAssistant runId="run-1" />)
    const user = await openPanel()
    await screen.findByLabelText(/ask a question/i)

    await user.type(screen.getByLabelText(/ask a question/i), 'What will next month look like?')
    await user.click(screen.getByRole('button', { name: /^send$/i }))

    expect(
      await screen.findByText('This question needs data outside this window’s findings.'),
    ).toBeInTheDocument()
    expect(screen.queryByText(/could not reach/i)).not.toBeInTheDocument()

    // The trace is still available for a withheld answer.
    expect(screen.getByRole('button', { name: /show trace/i })).toBeInTheDocument()
  })

  it('persists the conversation to localStorage, capped, and a later mount picks it up', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/api/ask')) return jsonResponse(makeResponse({ question: 'Why is on-time low this week?' }))
      return notFound()
    })
    vi.stubGlobal('fetch', fetchMock)

    const { unmount } = renderPanel(<FloatingAssistant runId="run-1" />)
    const user = await openPanel()
    await screen.findByLabelText(/ask a question/i)
    await user.click(screen.getByRole('button', { name: 'Why is on-time low this week?' }))
    await screen.findByText('Vendor A and Vendor C are dragging on-time down.')

    const stored = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? '[]')
    expect(stored).toHaveLength(1)

    unmount()

    // A fresh mount (simulating a route change, or a reload since this is
    // backed by localStorage, not just component state) reads the same
    // history back.
    renderPanel(<FloatingAssistant runId="run-1" />)
    await openPanel()
    expect(screen.getByText('Vendor A and Vendor C are dragging on-time down.')).toBeInTheDocument()
  })

  it('caps the persisted conversation at 50 exchanges, dropping the oldest', async () => {
    const seed = Array.from({ length: 50 }, (_, i) => ({
      id: `seed-${i}`,
      question: `question ${i}`,
      response: makeResponse({ answer: `answer ${i}`, trace: [] }),
      error: null,
    }))
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(seed))

    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/api/ask')) return jsonResponse(makeResponse({ answer: 'the 51st answer', trace: [] }))
      return notFound()
    })
    vi.stubGlobal('fetch', fetchMock)

    renderPanel(<FloatingAssistant runId="run-1" />)
    const user = await openPanel()
    await screen.findByLabelText(/ask a question/i)

    await user.type(screen.getByLabelText(/ask a question/i), 'one more question')
    await user.click(screen.getByRole('button', { name: /^send$/i }))

    await waitFor(() => {
      const stored = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? '[]')
      expect(stored).toHaveLength(50)
      expect(stored[0].id).toBe('seed-1') // seed-0 fell off
      expect(stored.at(-1).response.answer).toBe('the 51st answer')
    })
  })

  it('renders an error message (not withheld) when the request itself fails', async () => {
    // A 500 from /api/ask -- distinguishes "the service failed to answer"
    // from "the assistant chose not to answer", and leaves the feature on.
    stubFetch({
      health: () => healthResponse(['ask']),
      ask: () => errorResponse(500, 'Internal Server Error'),
    })

    renderPanel(<FloatingAssistant runId="run-1" />)
    const user = await openPanel()
    await screen.findByLabelText(/ask a question/i)

    await user.type(screen.getByLabelText(/ask a question/i), 'a question that will fail')
    await user.click(screen.getByRole('button', { name: /^send$/i }))

    expect(await screen.findByText(/could not reach the assistant/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/ask a question/i)).toBeEnabled()
  })

  it('offers a link into the full chat page, which the conversation is already in', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/api/ask')) return jsonResponse(makeResponse())
      return notFound()
    })
    vi.stubGlobal('fetch', fetchMock)

    renderPanel(<FloatingAssistant runId="run-1" />)
    const user = await openPanel()
    await screen.findByLabelText(/ask a question/i)
    await user.click(screen.getByRole('button', { name: 'Why is on-time low this week?' }))
    await screen.findByText('Vendor A and Vendor C are dragging on-time down.')

    const expand = screen.getByRole('link', { name: /expand/i })
    expect(expand).toHaveAttribute('href', '/chat')

    // Nothing is handed over on the click: the exchange is already in the
    // shared store, which is what the chat page reads on mount.
    const stored = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? '[]')
    expect(stored.at(-1).response.answer).toBe('Vendor A and Vendor C are dragging on-time down.')
  })

  it('renders every control as the shared Button component', async () => {
    vi.stubGlobal('fetch', vi.fn(() => notFound()))
    const { container } = renderPanel(<FloatingAssistant runId="run-1" />)
    await openPanel()

    const dialog = within(screen.getByRole('dialog'))
    for (const button of container.querySelectorAll('button')) {
      expect(button.classList.contains('btn')).toBe(true)
    }
    expect(dialog.getByRole('button', { name: /close/i })).toBeInTheDocument()
  })
})
