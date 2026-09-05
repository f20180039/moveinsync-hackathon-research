import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AskResponse } from '../api/types.ts'
import { loadSessions, saveCurrentTurns } from '../chat.ts'
import type { ChatTurn } from '../chat.ts'
import { ChatPage } from './ChatPage.tsx'

function jsonResponse(body: unknown) {
  return Promise.resolve({ ok: true, json: async () => body } as Response)
}

function notFound() {
  return Promise.resolve({ ok: false, status: 404, statusText: 'Not Found', text: async () => '' } as Response)
}

function healthResponse(capabilities?: string[]) {
  return jsonResponse({
    status: 'ok',
    activeMetrics: ['ota'],
    clock: '2026-09-05T09:00:00Z',
    ...(capabilities !== undefined && { capabilities }),
  })
}

function makeResponse(overrides: Partial<AskResponse> = {}): AskResponse {
  return {
    runId: 'latest',
    question: 'Why is on-time low this week?',
    answer: 'Vendor A and Vendor C are dragging on-time down.',
    withheld: false,
    reason: null,
    trace: [{ tool: 'query_findings', arguments: { metric: 'ota' }, result: { rows: 2 } }],
    ...overrides,
  }
}

function stubFetch(routes: { health?: () => Promise<Response>; ask?: () => Promise<Response> }) {
  const fetchMock = vi.fn((input: RequestInfo | URL, _init?: RequestInit) => {
    const url = String(input)
    if (url.includes('/api/health')) return routes.health?.() ?? notFound()
    if (url.includes('/api/ask')) return routes.ask?.() ?? notFound()
    return notFound()
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function turn(question: string, answer: string): ChatTurn {
  return { id: `id-${question}`, question, response: makeResponse({ question, answer, trace: [] }), error: null }
}

function askBody(fetchMock: ReturnType<typeof stubFetch>) {
  const call = fetchMock.mock.calls.find(([input]) => String(input).includes('/api/ask'))
  return JSON.parse(String(call?.[1]?.body))
}

beforeEach(() => {
  window.localStorage.clear()
})

afterEach(() => {
  vi.unstubAllGlobals()
  window.localStorage.clear()
})

describe('ChatPage', () => {
  it('renders one centred column with the composer focused, ready to type into', async () => {
    stubFetch({ health: () => healthResponse(['ask']) })
    const { container } = render(<ChatPage />)

    expect(container.querySelector('.chat-page__column')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /mobility intelligence/i, level: 1 })).toBeInTheDocument()
    expect(screen.getByLabelText(/ask a question/i)).toHaveFocus()
    await waitFor(() => expect(screen.getByLabelText(/ask a question/i)).toBeEnabled())
  })

  it('offers the grounded starter questions while the conversation is empty', async () => {
    const fetchMock = stubFetch({
      health: () => healthResponse(['ask']),
      ask: () => jsonResponse(makeResponse({ answer: 'Vendor C is worst on on-time.' })),
    })
    render(<ChatPage />)
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: 'Which vendor is worst on on-time?' }))

    expect(await screen.findByText('Vendor C is worst on on-time.')).toBeInTheDocument()
    expect(askBody(fetchMock)).toEqual({ runId: 'latest', question: 'Which vendor is worst on on-time?' })
    // Once there is a conversation, the starters are out of the way.
    expect(screen.queryByRole('button', { name: 'Summarise this week' })).not.toBeInTheDocument()
  })

  it('sends on Enter, and renders the answer with a trace that is collapsed by default', async () => {
    stubFetch({ health: () => healthResponse(['ask']), ask: () => jsonResponse(makeResponse()) })
    render(<ChatPage />)
    const user = userEvent.setup()

    const input = await screen.findByLabelText(/ask a question/i)
    await user.type(input, 'Why is on-time low this week?')
    await user.keyboard('{Enter}')

    expect(await screen.findByText('Vendor A and Vendor C are dragging on-time down.')).toBeInTheDocument()
    // Grounding is the product: the trace is one click away, never gone.
    expect(screen.queryByText(/query_findings/)).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /show trace/i }))
    expect(screen.getByText(/query_findings/)).toBeInTheDocument()
  })

  it('Shift+Enter is a newline, not a send', async () => {
    const fetchMock = stubFetch({ health: () => healthResponse(['ask']), ask: () => jsonResponse(makeResponse()) })
    render(<ChatPage />)
    const user = userEvent.setup()

    const input = await screen.findByLabelText(/ask a question/i)
    await user.type(input, 'half a question')
    await user.keyboard('{Shift>}{Enter}{/Shift}')

    expect(fetchMock.mock.calls.filter(([i]) => String(i).includes('/api/ask'))).toHaveLength(0)
    expect(input).toHaveValue('half a question\n')
  })

  it('carries the prior turns to the service as `history`, oldest first', async () => {
    saveCurrentTurns([turn('why is on-time low?', 'Vendor C slipped.')])
    const fetchMock = stubFetch({
      health: () => healthResponse(['ask']),
      ask: () => jsonResponse(makeResponse({ answer: 'It was 91% the week before.' })),
    })
    render(<ChatPage />)
    const user = userEvent.setup()

    const input = await screen.findByLabelText(/ask a question/i)
    await user.type(input, 'and the week before?')
    await user.keyboard('{Enter}')

    await screen.findByText('It was 91% the week before.')
    expect(askBody(fetchMock)).toEqual({
      runId: 'latest',
      question: 'and the week before?',
      history: [
        { role: 'user', content: 'why is on-time low?' },
        { role: 'assistant', content: 'Vendor C slipped.' },
      ],
    })
  })

  it('restores the conversation on a reload, which is what a persisted session buys', async () => {
    saveCurrentTurns([turn('why is on-time low?', 'Vendor C slipped.')])
    stubFetch({ health: () => healthResponse(['ask']) })

    render(<ChatPage />)

    expect(screen.getByText('why is on-time low?')).toBeInTheDocument()
    expect(screen.getByText('Vendor C slipped.')).toBeInTheDocument()
  })

  it('"New chat" files the conversation away and starts empty, and it can be resumed', async () => {
    saveCurrentTurns([turn('why is on-time low?', 'Vendor C slipped.')])
    stubFetch({ health: () => healthResponse(['ask']) })
    render(<ChatPage />)
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: /new chat/i }))

    expect(screen.queryByText('Vendor C slipped.')).not.toBeInTheDocument()
    expect(screen.getByText("Ask a question about this window's findings.")).toBeInTheDocument()
    expect(loadSessions()).toHaveLength(1)

    await user.click(screen.getByRole('button', { name: 'why is on-time low?' }))

    expect(screen.getByText('Vendor C slipped.')).toBeInTheDocument()
  })

  it('renders a withheld answer as its reason, with the trace still available', async () => {
    stubFetch({
      health: () => healthResponse(['ask']),
      ask: () =>
        jsonResponse(
          makeResponse({ answer: null, withheld: true, reason: 'That needs data outside this window.' }),
        ),
    })
    render(<ChatPage />)
    const user = userEvent.setup()

    const input = await screen.findByLabelText(/ask a question/i)
    await user.type(input, 'What will next month look like?')
    await user.keyboard('{Enter}')

    expect(await screen.findByText('That needs data outside this window.')).toBeInTheDocument()
    expect(screen.queryByText(/could not reach/i)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /show trace/i })).toBeInTheDocument()
  })

  it('a 500 is one failed question -- the composer stays enabled to retry', async () => {
    stubFetch({
      health: () => healthResponse(['ask']),
      ask: () =>
        Promise.resolve({ ok: false, status: 500, statusText: 'Server Error', text: async () => '' } as Response),
    })
    render(<ChatPage />)
    const user = userEvent.setup()

    const input = await screen.findByLabelText(/ask a question/i)
    await user.type(input, 'a question that fails')
    await user.keyboard('{Enter}')

    expect(await screen.findByText(/could not reach the assistant/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/ask a question/i)).toBeEnabled()
  })

  it('a 404 from /api/ask turns the page off, because this build serves no assistant', async () => {
    stubFetch({ health: () => healthResponse(['ask']), ask: () => notFound() })
    render(<ChatPage />)
    const user = userEvent.setup()

    const input = await screen.findByLabelText(/ask a question/i)
    await user.type(input, 'a question to an endpoint that is gone')
    await user.keyboard('{Enter}')

    expect(await screen.findByText(/does not serve the assistant endpoint/i)).toBeInTheDocument()
    await waitFor(() => expect(screen.getByLabelText(/ask a question/i)).toBeDisabled())
  })

  it('renders every control as the shared Button component', async () => {
    stubFetch({ health: () => healthResponse(['ask']) })
    const { container } = render(<ChatPage />)
    await screen.findByLabelText(/ask a question/i)

    for (const button of container.querySelectorAll('button')) {
      expect(button.classList.contains('btn')).toBe(true)
    }
  })
})
