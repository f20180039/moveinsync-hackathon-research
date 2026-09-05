import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AskResponse } from '../api/types.ts'
import { FloatingAssistant } from './FloatingAssistant.tsx'

const STORAGE_KEY = 'signal-desk:assistant-conversation'

function notFound() {
  return Promise.resolve({ ok: false, status: 404, statusText: 'Not Found', text: async () => '' } as Response)
}

function jsonResponse(body: unknown) {
  return Promise.resolve({ ok: true, json: async () => body } as Response)
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
    render(<FloatingAssistant runId="run-1" />)

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /open mobility intelligence assistant/i })).toBeInTheDocument()
  })

  it('opens a non-modal dialog panel on click', async () => {
    vi.stubGlobal('fetch', vi.fn(() => notFound()))
    render(<FloatingAssistant runId="run-1" />)

    await openPanel()

    const dialog = screen.getByRole('dialog', { name: /mobility intelligence assistant/i })
    expect(dialog).toHaveAttribute('aria-modal', 'false')
  })

  it('shows the four default suggested chips', async () => {
    vi.stubGlobal('fetch', vi.fn(() => notFound()))
    render(<FloatingAssistant runId="run-1" />)
    await openPanel()

    expect(screen.getByRole('button', { name: 'Why is on-time low this week?' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Which vendor is underperforming?' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Where are no-shows concentrated?' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'What changed vs last week?' })).toBeInTheDocument()
  })

  it('accepts an override list of suggested questions (Stage 7 role-specific chips)', async () => {
    vi.stubGlobal('fetch', vi.fn(() => notFound()))
    render(<FloatingAssistant runId="run-1" suggestedQuestions={['Which vendors are recurring laggards?']} />)
    await openPanel()

    expect(screen.getByRole('button', { name: 'Which vendors are recurring laggards?' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Which vendor is underperforming?' })).not.toBeInTheDocument()
  })

  it('disables the input with helper text when /api/ask 404s', async () => {
    vi.stubGlobal('fetch', vi.fn(() => notFound()))
    render(<FloatingAssistant runId="run-1" />)
    await openPanel()

    expect(await screen.findByText('Interrogation lands with the tools — coming')).toBeInTheDocument()
    expect(screen.getByLabelText(/ask a question/i)).toBeDisabled()
  })

  it('Escape closes the panel and returns focus to the launcher', async () => {
    vi.stubGlobal('fetch', vi.fn(() => notFound()))
    render(<FloatingAssistant runId="run-1" />)
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

    render(<FloatingAssistant runId="run-1" />)
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

    render(<FloatingAssistant runId="run-1" />)
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

    const { unmount } = render(<FloatingAssistant runId="run-1" />)
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
    render(<FloatingAssistant runId="run-1" />)
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

    render(<FloatingAssistant runId="run-1" />)
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
    // /api/ask 404s on the *real* question, after the mount-time empty-
    // question probe already reported it as available (an inconsistent
    // service, or a transient failure) -- distinguishes "the service
    // failed to answer" from "the assistant chose not to answer".
    let call = 0
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/api/ask')) {
        call += 1
        return call === 1 ? jsonResponse(makeResponse()) : notFound()
      }
      return notFound()
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<FloatingAssistant runId="run-1" />)
    const user = await openPanel()
    await screen.findByLabelText(/ask a question/i)

    await user.type(screen.getByLabelText(/ask a question/i), 'a question that will fail')
    await user.click(screen.getByRole('button', { name: /^send$/i }))

    expect(await screen.findByText(/could not reach the assistant/i)).toBeInTheDocument()
  })

  it('renders every control as the shared Button component', async () => {
    vi.stubGlobal('fetch', vi.fn(() => notFound()))
    const { container } = render(<FloatingAssistant runId="run-1" />)
    await openPanel()

    const dialog = within(screen.getByRole('dialog'))
    for (const button of container.querySelectorAll('button')) {
      expect(button.classList.contains('btn')).toBe(true)
    }
    expect(dialog.getByRole('button', { name: /close/i })).toBeInTheDocument()
  })
})
