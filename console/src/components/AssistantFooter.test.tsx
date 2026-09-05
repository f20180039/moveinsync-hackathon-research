import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AskResponse } from '../api/types.ts'
import { loadSessions } from '../chat.ts'
import { AssistantFooter } from './AssistantFooter.tsx'

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

// What the deployed service answers once the run the console loaded has
// aged out of its in-process store -- a 404 that names the missing RUN.
function staleRunResponse(runId: string) {
  return Promise.resolve({
    ok: false,
    status: 404,
    statusText: 'Not Found',
    text: async () => JSON.stringify({ detail: { error: `no run '${runId}'` } }),
  } as Response)
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
function stubFetch(routes: { health?: () => Promise<Response>; ask?: (init?: RequestInit) => Promise<Response> }) {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.includes('/api/health')) return routes.health?.() ?? notFound()
    if (url.includes('/api/ask')) return routes.ask?.(init) ?? notFound()
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

function askBody(fetchMock: ReturnType<typeof stubFetch>, nth = 0) {
  const calls = fetchMock.mock.calls.filter(([input]) => String(input).includes('/api/ask'))
  return JSON.parse(String(calls[nth]?.[1]?.body))
}

async function expand() {
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: /expand/i }))
  return user
}

beforeEach(() => {
  window.localStorage.clear()
})

afterEach(() => {
  vi.unstubAllGlobals()
  window.localStorage.clear()
})

describe('AssistantFooter', () => {
  it('is a slim composer bar by default -- no conversation, no launcher to find', () => {
    stubFetch({ health: () => healthResponse(['ask']) })
    const { container } = render(<AssistantFooter runId="run-1" />)

    expect(container.querySelector('.assistant-footer__bar')).toBeInTheDocument()
    expect(container.querySelector('.assistant-footer__panel')).not.toBeInTheDocument()
    expect(screen.getByLabelText(/ask about this run/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /expand/i })).toHaveAttribute('aria-expanded', 'false')
  })

  it('expands into the centred conversation and collapses back to the bar', async () => {
    stubFetch({ health: () => healthResponse(['ask']) })
    const { container } = render(<AssistantFooter runId="run-1" />)

    const user = await expand()

    expect(container.querySelector('.assistant-footer__panel')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /mobility intelligence/i })).toBeInTheDocument()
    // The composer is the same one in both states -- it does not move.
    expect(screen.getByLabelText(/ask about this run/i)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /collapse/i }))
    expect(container.querySelector('.assistant-footer__panel')).not.toBeInTheDocument()
  })

  it('Escape collapses the expanded conversation', async () => {
    stubFetch({ health: () => healthResponse(['ask']) })
    const { container } = render(<AssistantFooter runId="run-1" />)
    const user = await expand()

    await user.keyboard('{Escape}')

    expect(container.querySelector('.assistant-footer__panel')).not.toBeInTheDocument()
  })

  it('shows the four default suggested chips once expanded', async () => {
    stubFetch({ health: () => healthResponse(['ask']) })
    render(<AssistantFooter runId="run-1" />)
    await expand()

    expect(screen.getByRole('button', { name: 'Why is on-time low this week?' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Which vendor is worst on on-time?' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Where are no-shows concentrated?' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Summarise this week' })).toBeInTheDocument()
  })

  it('accepts an override list of suggested questions (the Facilities head chips)', async () => {
    stubFetch({ health: () => healthResponse(['ask']) })
    render(<AssistantFooter runId="run-1" suggestedQuestions={['Which vendors are recurring laggards?']} />)
    await expand()

    expect(screen.getByRole('button', { name: 'Which vendors are recurring laggards?' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Which vendor is worst on on-time?' })).not.toBeInTheDocument()
  })

  it('clicking a suggestion asks exactly that question', async () => {
    const fetchMock = stubFetch({
      health: () => healthResponse(['ask']),
      ask: () => jsonResponse(makeResponse({ answer: 'Vendor C is worst on on-time.' })),
    })
    render(<AssistantFooter runId="run-1" />)
    const user = await expand()

    await user.click(screen.getByRole('button', { name: 'Which vendor is worst on on-time?' }))

    expect(await screen.findByText('Vendor C is worst on on-time.')).toBeInTheDocument()
    expect(askBody(fetchMock)).toEqual({ runId: 'run-1', question: 'Which vendor is worst on on-time?' })
  })

  it('a question typed into the slim bar expands the footer, because the answer needs somewhere to land', async () => {
    stubFetch({ health: () => healthResponse(['ask']), ask: () => jsonResponse(makeResponse()) })
    const { container } = render(<AssistantFooter runId="run-1" />)
    const user = userEvent.setup()

    await user.type(screen.getByLabelText(/ask about this run/i), 'Why is on-time low this week?')
    await user.keyboard('{Enter}')

    expect(await screen.findByText('Vendor A and Vendor C are dragging on-time down.')).toBeInTheDocument()
    expect(container.querySelector('.assistant-footer__panel')).toBeInTheDocument()
  })

  it('renders the answer with its tool trace, collapsed until asked for', async () => {
    stubFetch({ health: () => healthResponse(['ask']), ask: () => jsonResponse(makeResponse()) })
    render(<AssistantFooter runId="run-1" />)
    const user = await expand()

    await user.click(screen.getByRole('button', { name: 'Why is on-time low this week?' }))
    await screen.findByText('Vendor A and Vendor C are dragging on-time down.')

    // Grounding is the product: the trace is one click away, never gone.
    expect(screen.queryByText(/query_findings/)).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /show trace/i }))
    expect(screen.getByText(/query_findings/)).toBeInTheDocument()
  })

  it('Shift+Enter is a newline, not a send', async () => {
    const fetchMock = stubFetch({ health: () => healthResponse(['ask']), ask: () => jsonResponse(makeResponse()) })
    render(<AssistantFooter runId="run-1" />)
    const user = userEvent.setup()

    const input = screen.getByLabelText(/ask about this run/i)
    await user.type(input, 'half a question')
    await user.keyboard('{Shift>}{Enter}{/Shift}')

    expect(fetchMock.mock.calls.filter(([i]) => String(i).includes('/api/ask'))).toHaveLength(0)
    expect(input).toHaveValue('half a question\n')
  })

  it('carries the prior turns to the service as `history`, oldest first', async () => {
    const fetchMock = stubFetch({
      health: () => healthResponse(['ask']),
      ask: () => jsonResponse(makeResponse({ answer: 'Vendor C slipped.' })),
    })
    render(<AssistantFooter runId="run-1" />)
    const user = await expand()

    await user.click(screen.getByRole('button', { name: 'Why is on-time low this week?' }))
    await screen.findByText('Vendor C slipped.')

    await user.type(screen.getByLabelText(/ask about this run/i), 'and the week before?')
    await user.keyboard('{Enter}')

    await waitFor(() => expect(askBody(fetchMock, 1).question).toBe('and the week before?'))
    expect(askBody(fetchMock, 1).history).toEqual([
      { role: 'user', content: 'Why is on-time low this week?' },
      { role: 'assistant', content: 'Vendor C slipped.' },
    ])
  })

  it('disables the composer when /api/health advertises capabilities without "ask"', async () => {
    stubFetch({ health: () => healthResponse(['decompose', 'safety', 'employees']) })
    render(<AssistantFooter runId="run-1" />)

    expect(await screen.findByText('Interrogation lands with the tools — coming')).toBeInTheDocument()
    expect(screen.getByLabelText(/ask about this run/i)).toBeDisabled()
  })

  it('stays available when /api/health omits `capabilities` entirely (older service)', async () => {
    // Absence of evidence is not evidence of absence: a service that
    // predates the field still serves /api/ask.
    stubFetch({ health: () => healthResponse(undefined) })
    render(<AssistantFooter runId="run-1" />)

    await waitFor(() => expect(screen.getByLabelText(/ask about this run/i)).toBeEnabled())
    expect(screen.queryByText('Interrogation lands with the tools — coming')).not.toBeInTheDocument()
  })

  it('never probes /api/ask to feature-detect -- no request is sent until a question is asked', async () => {
    const fetchMock = stubFetch({ health: () => healthResponse(['ask']) })
    render(<AssistantFooter runId="run-1" />)

    await waitFor(() => expect(fetchMock).toHaveBeenCalled())
    expect(fetchMock.mock.calls.filter(([input]) => String(input).includes('/api/ask'))).toHaveLength(0)
  })

  it('leaves the composer ENABLED when /api/ask answers 422, and surfaces the failure on that question', async () => {
    // The regression this locks: a 422 is a rejected question, not a
    // missing endpoint. The console used to disable the whole assistant.
    stubFetch({ health: () => healthResponse(['ask']), ask: () => errorResponse(422, 'Unprocessable Entity') })
    render(<AssistantFooter runId="run-1" />)
    const user = userEvent.setup()

    await user.type(screen.getByLabelText(/ask about this run/i), 'a question the service rejects')
    await user.keyboard('{Enter}')

    expect(await screen.findByText(/could not reach the assistant/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/ask about this run/i)).toBeEnabled()
    expect(screen.queryByText('Interrogation lands with the tools — coming')).not.toBeInTheDocument()
  })

  it('recovers when the run the console loaded has aged out of the service', async () => {
    // The reported bug: the console holds the run id it fetched at startup,
    // the service sweeps on and drops it, and the resulting 404 -- which
    // names the missing RUN, not a missing route -- was reported as "this
    // build does not serve the assistant endpoint" and disabled the
    // assistant for the rest of the session.
    stubFetch({
      health: () => healthResponse(['ask']),
      ask: (init) => {
        const body = JSON.parse(String(init?.body))
        if (body.runId === 'latest') return jsonResponse(makeResponse({ answer: 'On-time fell to 88%.' }))
        return staleRunResponse(body.runId)
      },
    })
    render(<AssistantFooter runId="run-1785542400000-b0" />)
    const user = userEvent.setup()

    await user.type(screen.getByLabelText(/ask about this run/i), 'why did on-time fall?')
    await user.keyboard('{Enter}')

    expect(await screen.findByText('On-time fell to 88%.')).toBeInTheDocument()
    expect(screen.queryByText(/does not serve the assistant endpoint/i)).not.toBeInTheDocument()
    expect(screen.getByLabelText(/ask about this run/i)).toBeEnabled()
  })

  it('disables the assistant when /api/ask itself answers 404 naming no run at all', async () => {
    stubFetch({ health: () => healthResponse(['ask']), ask: () => notFound() })
    render(<AssistantFooter runId="run-1" />)
    const user = userEvent.setup()

    await user.type(screen.getByLabelText(/ask about this run/i), 'a question to an endpoint that is gone')
    await user.keyboard('{Enter}')

    expect(await screen.findByText(/does not serve the assistant endpoint/i)).toBeInTheDocument()
    await waitFor(() => expect(screen.getByLabelText(/ask about this run/i)).toBeDisabled())
  })

  it('renders a withheld answer as the reason and trace, not an error', async () => {
    stubFetch({
      health: () => healthResponse(['ask']),
      ask: () =>
        jsonResponse(
          makeResponse({
            answer: null,
            withheld: true,
            reason: 'This question needs data outside this window’s findings.',
          }),
        ),
    })
    render(<AssistantFooter runId="run-1" />)
    const user = userEvent.setup()

    await user.type(screen.getByLabelText(/ask about this run/i), 'What will next month look like?')
    await user.keyboard('{Enter}')

    expect(await screen.findByText('This question needs data outside this window’s findings.')).toBeInTheDocument()
    expect(screen.queryByText(/could not reach/i)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /show trace/i })).toBeInTheDocument()
  })

  it('shows the service\u2019s friendly message on a refusal, with the diagnostic in the detail', async () => {
    stubFetch({
      health: () => healthResponse(['ask']),
      ask: () =>
        jsonResponse(
          makeResponse({
            answer: null,
            withheld: true,
            reason: 'answer contained a figure no tool returned: 14.8',
            message: 'I held this answer back. One of the numbers in it did not match anything the data returned.',
          }),
        ),
    })
    render(<AssistantFooter runId="run-1" />)
    const user = userEvent.setup()

    await user.type(screen.getByLabelText(/ask about this run/i), 'review this week')
    await user.keyboard('{Enter}')

    expect(
      await screen.findByText(
        'I held this answer back. One of the numbers in it did not match anything the data returned.',
      ),
    ).toBeInTheDocument()
    expect(screen.queryByText(/no tool returned: 14.8/)).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /show trace/i }))
    expect(screen.getByText('answer contained a figure no tool returned: 14.8')).toBeInTheDocument()
  })

  it('persists the conversation, and a later mount picks it up', async () => {
    stubFetch({ health: () => healthResponse(['ask']), ask: () => jsonResponse(makeResponse()) })
    const { unmount } = render(<AssistantFooter runId="run-1" />)
    const user = await expand()

    await user.click(screen.getByRole('button', { name: 'Why is on-time low this week?' }))
    await screen.findByText('Vendor A and Vendor C are dragging on-time down.')

    expect(JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? '[]')).toHaveLength(1)

    unmount()

    // A fresh mount (a route change tears nothing down, but a reload does)
    // reads the same conversation back.
    render(<AssistantFooter runId="run-1" />)
    await expand()
    expect(screen.getByText('Vendor A and Vendor C are dragging on-time down.')).toBeInTheDocument()
  })

  it('caps the persisted conversation at 50 turns, dropping the oldest', async () => {
    const seed = Array.from({ length: 50 }, (_, i) => ({
      id: `seed-${i}`,
      question: `question ${i}`,
      response: makeResponse({ answer: `answer ${i}`, trace: [] }),
      error: null,
    }))
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(seed))
    stubFetch({
      health: () => healthResponse(['ask']),
      ask: () => jsonResponse(makeResponse({ answer: 'the 51st answer', trace: [] })),
    })

    render(<AssistantFooter runId="run-1" />)
    const user = userEvent.setup()

    await user.type(screen.getByLabelText(/ask about this run/i), 'one more question')
    await user.keyboard('{Enter}')

    await waitFor(() => {
      const stored = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? '[]')
      expect(stored).toHaveLength(50)
      expect(stored[0].id).toBe('seed-1') // seed-0 fell off
      expect(stored.at(-1).response.answer).toBe('the 51st answer')
    })
  })

  it('"New chat" files the conversation away, and it can be resumed', async () => {
    stubFetch({ health: () => healthResponse(['ask']), ask: () => jsonResponse(makeResponse()) })
    render(<AssistantFooter runId="run-1" />)
    const user = userEvent.setup()

    await user.type(screen.getByLabelText(/ask about this run/i), 'why did vendor C slip?')
    await user.keyboard('{Enter}')
    await screen.findByText('Vendor A and Vendor C are dragging on-time down.')

    await user.click(screen.getByRole('button', { name: /new chat/i }))

    expect(screen.queryByText('Vendor A and Vendor C are dragging on-time down.')).not.toBeInTheDocument()
    expect(loadSessions()).toHaveLength(1)

    // The archived conversation is listed by its first question, which is
    // what a person recognises it by, and clicking it brings it back.
    await user.click(screen.getByRole('button', { name: 'why did vendor C slip?' }))
    expect(screen.getByText('Vendor A and Vendor C are dragging on-time down.')).toBeInTheDocument()
  })

  it('renders every control as the shared Button component', async () => {
    stubFetch({ health: () => healthResponse(['ask']) })
    const { container } = render(<AssistantFooter runId="run-1" />)
    await expand()

    for (const button of container.querySelectorAll('button')) {
      expect(button.classList.contains('btn')).toBe(true)
    }
  })
})
