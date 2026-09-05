import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { AskResponse } from '../api/types.ts'
import type { ChatSession, ChatTurn } from '../chat.ts'
import { ChatConversation } from './ChatConversation.tsx'

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

function turn(overrides: Partial<ChatTurn> = {}): ChatTurn {
  return { id: 't1', question: 'Why is on-time low this week?', response: makeResponse(), error: null, ...overrides }
}

function renderConversation(props: Partial<Parameters<typeof ChatConversation>[0]> = {}) {
  const onAsk = vi.fn()
  const onNewChat = vi.fn()
  const onResume = vi.fn()
  const result = render(
    <ChatConversation
      turns={[]}
      sessions={[]}
      asking={false}
      available={true}
      suggestedQuestions={['Why is on-time low this week?', 'Summarise this week']}
      onAsk={onAsk}
      onNewChat={onNewChat}
      onResume={onResume}
      {...props}
    />,
  )
  return { ...result, onAsk, onNewChat, onResume }
}

describe('ChatConversation', () => {
  it('offers the starter questions while the conversation is empty', async () => {
    const { onAsk } = renderConversation()
    const user = userEvent.setup()

    expect(screen.getByText("Ask a question about this window's findings.")).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Summarise this week' }))

    expect(onAsk).toHaveBeenCalledWith('Summarise this week')
  })

  it('disables the starters when this build serves no assistant', () => {
    renderConversation({ available: false })
    expect(screen.getByRole('button', { name: 'Summarise this week' })).toBeDisabled()
  })

  it('distinguishes the question from the answer, and names who said each', () => {
    const { container } = renderConversation({ turns: [turn()] })

    const user = container.querySelector('.chat-message--user') as HTMLElement
    const assistant = container.querySelector('.chat-message--assistant') as HTMLElement
    expect(within(user).getByText('Why is on-time low this week?')).toBeInTheDocument()
    expect(within(assistant).getByText('Vendor A and Vendor C are dragging on-time down.')).toBeInTheDocument()
    // The starters are out of the way once there is a conversation.
    expect(screen.queryByRole('button', { name: 'Summarise this week' })).not.toBeInTheDocument()
  })

  it('keeps the tool trace one click away -- collapsed, never gone', async () => {
    renderConversation({ turns: [turn()] })
    const user = userEvent.setup()

    expect(screen.queryByText(/query_findings/)).not.toBeInTheDocument()
    const toggle = screen.getByRole('button', { name: /show trace \(1\)/i })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')

    await user.click(toggle)
    expect(screen.getByText(/query_findings/)).toBeInTheDocument()
  })

  it('renders a withheld answer as its reason, with the trace still available', () => {
    renderConversation({
      turns: [
        turn({
          response: makeResponse({ answer: null, withheld: true, reason: 'That needs data outside this window.' }),
        }),
      ],
    })

    expect(screen.getByText('That needs data outside this window.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /show trace/i })).toBeInTheDocument()
  })

  it('shows the service\'s plain-language message on a refusal, not the internal reason', async () => {
    renderConversation({
      turns: [
        turn({
          response: makeResponse({
            answer: null,
            withheld: true,
            reason: 'answer contained a figure no tool returned: 14.8',
            message: 'I held this answer back because one number could not be traced. Try a narrower question.',
          }),
        }),
      ],
    })
    const user = userEvent.setup()

    expect(
      screen.getByText('I held this answer back because one number could not be traced. Try a narrower question.'),
    ).toBeInTheDocument()
    // The diagnostic is NOT the headline...
    expect(screen.queryByText(/answer contained a figure no tool returned/)).not.toBeInTheDocument()
    // ...but it is one click away, with the trace, because it is the receipt.
    await user.click(screen.getByRole('button', { name: /show trace/i }))
    expect(screen.getByText('answer contained a figure no tool returned: 14.8')).toBeInTheDocument()
  })

  it('keeps the reason reachable even when the refusal spent no tool calls', async () => {
    renderConversation({
      turns: [
        turn({
          response: makeResponse({
            answer: null,
            withheld: true,
            reason: 'no SARVAM_API_KEY configured',
            message: 'The assistant is not switched on for this build.',
            trace: [],
          }),
        }),
      ],
    })
    const user = userEvent.setup()

    expect(screen.getByText('The assistant is not switched on for this build.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /show detail/i }))
    expect(screen.getByText('no SARVAM_API_KEY configured')).toBeInTheDocument()
  })

  it('falls back to the reason when the service sends no message', () => {
    // An older service that predates the field must render exactly as it
    // did before -- the reason as the headline, and not printed twice.
    renderConversation({
      turns: [turn({ response: makeResponse({ answer: null, withheld: true, reason: 'That needs data outside this window.' }) })],
    })

    expect(screen.getAllByText('That needs data outside this window.')).toHaveLength(1)
    expect(screen.getByRole('button', { name: /show trace \(1\)/i })).toBeInTheDocument()
  })

  it('shows no refusal detail at all on an answered turn', () => {
    renderConversation({ turns: [turn()] })
    expect(screen.getByRole('button', { name: /show trace \(1\)/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /show detail/i })).not.toBeInTheDocument()
  })

  it('renders a failed request as an error, which is a different thing from a withheld answer', () => {
    renderConversation({
      turns: [turn({ response: null, error: 'Could not reach the assistant -- try again in a moment.' })],
    })

    expect(screen.getByText(/could not reach the assistant/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /show trace/i })).not.toBeInTheDocument()
  })

  it('lists past conversations by their first question, and resumes the one clicked', async () => {
    const sessions: ChatSession[] = [
      { id: 's1', startedAt: '2026-09-04T09:00:00Z', turns: [turn({ question: 'why did vendor C slip?' })] },
    ]
    const { onResume } = renderConversation({ sessions })
    const user = userEvent.setup()

    await user.click(
      within(screen.getByRole('region', { name: /previous chats/i })).getByRole('button', {
        name: 'why did vendor C slip?',
      }),
    )

    expect(onResume).toHaveBeenCalledWith('s1')
  })

  it('shows that tools are running while an answer is in flight', () => {
    renderConversation({ asking: true })
    expect(screen.getByText(/working through the tools/i)).toBeInTheDocument()
  })

  it('starts a new chat on request', async () => {
    const { onNewChat } = renderConversation({ turns: [turn()] })
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: /new chat/i }))

    expect(onNewChat).toHaveBeenCalled()
  })
})
