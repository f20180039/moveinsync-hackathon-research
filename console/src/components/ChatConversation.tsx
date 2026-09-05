import { useEffect, useRef, useState } from 'react'
import type { AskResponse } from '../api/types.ts'
import { sessionTitle } from '../chat.ts'
import type { ChatSession, ChatTurn } from '../chat.ts'
import { Button } from './Button.tsx'

function TurnView({ turn }: { turn: ChatTurn }) {
  const [traceOpen, setTraceOpen] = useState(false)
  const { response, error } = turn
  const trace: AskResponse['trace'] = response?.trace ?? []

  // What the person reads: the service's own plain-language message, and --
  // when it is absent, which is exactly an older service that predates the
  // field -- today's behaviour unchanged.
  const withheldText = response?.message ?? response?.reason ?? 'The assistant withheld an answer for this question.'
  // The technical reason stays reachable rather than deleted: it is the
  // receipt that the guardrail fired, which is the point judges are here
  // for. Suppressed only when it is already the headline (the fallback
  // case), so it is never printed twice.
  const detailReason = response?.withheld && response.reason && response.reason !== withheldText ? response.reason : null
  const hasDetail = trace.length > 0 || detailReason !== null

  return (
    <div className="chat-turn">
      <div className="chat-message chat-message--user">
        <p className="chat-message__role">You</p>
        <p className="chat-message__text">{turn.question}</p>
      </div>

      <div className="chat-message chat-message--assistant">
        <p className="chat-message__role">Mobility Intelligence</p>

        {error && <p className="chat-message__error">{error}</p>}

        {response?.withheld && <p className="chat-message__withheld">{withheldText}</p>}

        {response && !response.withheld && <p className="chat-message__text">{response.answer}</p>}

        {/* The trace is what separates a grounded answer from a plausible
            one: every answer above came out of validated tool calls, and
            this is the receipt. Collapsed by default so the conversation
            reads as a conversation, one click from open. */}
        {hasDetail && (
          <div className="chat-message__trace-controls">
            <Button variant="ghost" size="sm" aria-expanded={traceOpen} onClick={() => setTraceOpen((v) => !v)}>
              {traceOpen ? 'Hide trace' : trace.length > 0 ? `Show trace (${trace.length})` : 'Show detail'}
            </Button>
            {traceOpen && detailReason && <p className="chat-message__reason">{detailReason}</p>}
            {traceOpen && trace.length > 0 && (
              <pre className="chat-message__trace">{JSON.stringify(trace, null, 2)}</pre>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

export interface ChatConversationProps {
  turns: ChatTurn[]
  sessions: ChatSession[]
  asking: boolean
  /** False only when /api/health says this build has no `ask` capability. */
  available: boolean | null
  suggestedQuestions: string[]
  onAsk: (question: string) => void
  onNewChat: () => void
  onResume: (sessionId: string) => void
}

// The conversation itself -- the centred column of messages, the resumable
// session list and the starter questions. It owns no state beyond which
// traces are open: the turns, the storage and the asking all belong to the
// assistant footer that mounts this, which is what lets the same rendering
// serve the slim bar's expanded view without a second code path.
export function ChatConversation({
  turns,
  sessions,
  asking,
  available,
  suggestedQuestions,
  onAsk,
  onNewChat,
  onResume,
}: ChatConversationProps) {
  const threadRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (threadRef.current) threadRef.current.scrollTop = threadRef.current.scrollHeight
  }, [turns, asking])

  return (
    <div className="chat-conversation">
      <header className="chat-conversation__header">
        <div>
          <h2 className="chat-conversation__title">Mobility Intelligence</h2>
          <p className="chat-conversation__subtitle">
            Answers come from validated tool calls over this window's findings — open the trace on any answer to see
            which.
          </p>
        </div>
        <Button variant="ghost" size="sm" onClick={onNewChat}>
          New chat
        </Button>
      </header>

      {sessions.length > 0 && (
        <section className="chat-conversation__sessions" aria-label="Previous chats">
          <h3 className="chat-conversation__sessions-title">Previous chats</h3>
          <div className="chat-conversation__sessions-list">
            {sessions.map((session) => (
              <Button key={session.id} variant="ghost" size="sm" onClick={() => onResume(session.id)}>
                {sessionTitle(session)}
              </Button>
            ))}
          </div>
        </section>
      )}

      <div className="chat-conversation__thread" ref={threadRef}>
        {turns.length === 0 ? (
          <div className="chat-conversation__empty">
            <p className="chat-conversation__empty-text">Ask a question about this window's findings.</p>
            <div className="chat-conversation__suggestions">
              {suggestedQuestions.map((suggestion) => (
                <Button
                  key={suggestion}
                  variant="ghost"
                  size="sm"
                  disabled={available === false}
                  onClick={() => onAsk(suggestion)}
                >
                  {suggestion}
                </Button>
              ))}
            </div>
          </div>
        ) : (
          turns.map((turn) => <TurnView key={turn.id} turn={turn} />)
        )}
        {asking && <p className="chat-conversation__thinking">Working through the tools…</p>}
      </div>
    </div>
  )
}
