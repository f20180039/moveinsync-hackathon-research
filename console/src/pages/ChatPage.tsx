import { useEffect, useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'
import { getCapabilities, hasCapability } from '../api/client.ts'
import type { AskResponse } from '../api/types.ts'
import {
  MAX_TURNS,
  askTurn,
  loadCurrentTurns,
  loadSessions,
  resumeSession,
  saveCurrentTurns,
  sessionTitle,
  startNewSession,
} from '../chat.ts'
import type { ChatSession, ChatTurn } from '../chat.ts'
import { Button } from '../components/Button.tsx'
import { ROLES } from '../roles.ts'
import { useAppStore } from '../store.ts'

// The chat page asks about the newest run rather than taking a run id as a
// prop: it is reachable from every route (and directly, by URL), including
// the ones App has no run for yet, and the service resolves "latest"
// itself. Nothing on this page is per-run except the answers.
const RUN_ID = 'latest'

function TurnView({ turn }: { turn: ChatTurn }) {
  const [traceOpen, setTraceOpen] = useState(false)
  const { response, error } = turn
  const trace: AskResponse['trace'] = response?.trace ?? []

  return (
    <div className="chat-turn">
      <div className="chat-message chat-message--user">
        <p className="chat-message__role">You</p>
        <p className="chat-message__text">{turn.question}</p>
      </div>

      <div className="chat-message chat-message--assistant">
        <p className="chat-message__role">Mobility Intelligence</p>

        {error && <p className="chat-message__error">{error}</p>}

        {response?.withheld && (
          <p className="chat-message__withheld">
            {response.reason ?? 'The assistant withheld an answer for this question.'}
          </p>
        )}

        {response && !response.withheld && <p className="chat-message__text">{response.answer}</p>}

        {/* The trace is what separates a grounded answer from a
            plausible one: every answer above came out of validated tool
            calls, and this is the receipt. Collapsed by default so the
            conversation reads as a conversation, one click from open. */}
        {trace.length > 0 && (
          <div className="chat-message__trace-controls">
            <Button variant="ghost" size="sm" aria-expanded={traceOpen} onClick={() => setTraceOpen((v) => !v)}>
              {traceOpen ? 'Hide trace' : `Show trace (${trace.length})`}
            </Button>
            {traceOpen && <pre className="chat-message__trace">{JSON.stringify(trace, null, 2)}</pre>}
          </div>
        )}
      </div>
    </div>
  )
}

// The assistant as a page rather than a corner panel: one centred column,
// the conversation stacked in it and the composer pinned at the bottom.
// It shares its storage (and its ask/error mapping) with the floating
// panel through chat.ts, so a question asked in the panel is already here
// when the user expands it, and vice versa.
export function ChatPage() {
  const role = useAppStore((state) => state.role)
  const suggestedQuestions = (ROLES[role] ?? ROLES.TRANSPORT_MANAGER).suggestedQuestions

  const [turns, setTurns] = useState<ChatTurn[]>(() => loadCurrentTurns())
  const [sessions, setSessions] = useState<ChatSession[]>(() => loadSessions())
  const [question, setQuestion] = useState('')
  const [asking, setAsking] = useState(false)
  const [available, setAvailable] = useState<boolean | null>(null)

  const inputRef = useRef<HTMLTextAreaElement>(null)
  const threadRef = useRef<HTMLDivElement>(null)

  // Same feature detection as the floating panel: read GET /api/health's
  // capabilities list, never probe /api/ask (a 422 to a probe is not the
  // same fact as a 404 to a real question).
  useEffect(() => {
    let ignore = false
    // oxlint-disable-next-line react/set-state-in-effect
    getCapabilities().then((capabilities) => {
      if (!ignore) setAvailable(hasCapability(capabilities, 'ask'))
    })
    return () => {
      ignore = true
    }
  }, [])

  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  useEffect(() => {
    if (threadRef.current) threadRef.current.scrollTop = threadRef.current.scrollHeight
  }, [turns])

  async function submit(text: string) {
    const trimmed = text.trim()
    if (!trimmed || asking) return
    setQuestion('')
    setAsking(true)
    const outcome = await askTurn(RUN_ID, trimmed, turns)
    setAsking(false)
    if (outcome.endpointMissing) setAvailable(false)
    setTurns(appendAndPersist(outcome.turn))
    inputRef.current?.focus()
  }

  // Appends through the store rather than to local state, so what is
  // rendered and what is persisted cannot disagree (and the cap applies
  // in exactly one place).
  function appendAndPersist(turn: ChatTurn): ChatTurn[] {
    const next = [...turns, turn].slice(-MAX_TURNS)
    saveCurrentTurns(next)
    return next
  }

  function onNewChat() {
    setTurns(startNewSession())
    setSessions(loadSessions())
    inputRef.current?.focus()
  }

  function onResume(id: string) {
    setTurns(resumeSession(id))
    setSessions(loadSessions())
  }

  function onComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    // Enter sends, Shift+Enter is a newline -- the convention every chat
    // interface has trained people on.
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      submit(question)
    }
  }

  return (
    <div className="chat-page">
      <div className="chat-page__column">
        <header className="chat-page__header">
          <div>
            <h1 className="chat-page__title">Mobility Intelligence</h1>
            <p className="chat-page__subtitle">
              Answers come from validated tool calls over this window's findings — open the trace on any answer to see
              which.
            </p>
          </div>
          <Button variant="ghost" size="sm" onClick={onNewChat}>
            New chat
          </Button>
        </header>

        {sessions.length > 0 && (
          <section className="chat-page__sessions" aria-label="Previous chats">
            <h2 className="chat-page__sessions-title">Previous chats</h2>
            <div className="chat-page__sessions-list">
              {sessions.map((session) => (
                <Button key={session.id} variant="ghost" size="sm" onClick={() => onResume(session.id)}>
                  {sessionTitle(session)}
                </Button>
              ))}
            </div>
          </section>
        )}

        <div className="chat-page__thread" ref={threadRef}>
          {turns.length === 0 ? (
            <div className="chat-page__empty">
              <p className="chat-page__empty-text">Ask a question about this window's findings.</p>
              <div className="chat-page__suggestions">
                {suggestedQuestions.map((suggestion) => (
                  <Button
                    key={suggestion}
                    variant="ghost"
                    size="sm"
                    disabled={available === false}
                    onClick={() => submit(suggestion)}
                  >
                    {suggestion}
                  </Button>
                ))}
              </div>
            </div>
          ) : (
            turns.map((turn) => <TurnView key={turn.id} turn={turn} />)
          )}
          {asking && <p className="chat-page__thinking">Working through the tools…</p>}
        </div>

        <form
          className="chat-page__composer"
          onSubmit={(event) => {
            event.preventDefault()
            submit(question)
          }}
        >
          <label className="field__label" htmlFor="chat-page-input">
            Ask a question about this window's findings
          </label>
          <div className="chat-page__composer-row">
            <textarea
              id="chat-page-input"
              className="chat-page__input"
              ref={inputRef}
              rows={2}
              value={question}
              disabled={available === false}
              placeholder={
                available === false
                  ? 'Why did on-time fall this week?'
                  : 'Ask Mobility Intelligence… "Why did on-time fall this week?"'
              }
              onChange={(event) => setQuestion(event.target.value)}
              onKeyDown={onComposerKeyDown}
            />
            <Button type="submit" busy={asking} disabled={available === false || !question.trim()}>
              Send
            </Button>
          </div>
          {available === false && <p className="chat-page__helper">Interrogation lands with the tools — coming</p>}
        </form>
      </div>
    </div>
  )
}
