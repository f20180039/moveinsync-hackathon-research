import { useEffect, useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'
import { getCapabilities, hasCapability } from '../api/client.ts'
import { DEFAULT_SUGGESTED_QUESTIONS } from '../api/insights.ts'
import { MAX_TURNS, askTurn, loadCurrentTurns, loadSessions, resumeSession, saveCurrentTurns, startNewSession } from '../chat.ts'
import type { ChatSession, ChatTurn } from '../chat.ts'
import { Button } from './Button.tsx'
import { ChatConversation } from './ChatConversation.tsx'

export interface AssistantFooterProps {
  runId: string
  /** Overridable per role (the Facilities head persona swaps the second
   * chip) -- defaults to the standard four. */
  suggestedQuestions?: string[]
}

// The assistant as a sticky footer on every page: a slim composer bar
// pinned to the bottom of the viewport, which grows upward into the full
// centred conversation when it is expanded. It replaces both the corner
// launcher and the separate /chat tab -- one way in, from wherever the
// operator already is, and nothing to navigate away from.
//
// Mounted once at the App shell level (not per-page), so a question asked
// on Overview is still on screen after clicking through to Vendors. The
// conversation is persisted by chat.ts, so it also survives a reload.
export function AssistantFooter({ runId, suggestedQuestions = DEFAULT_SUGGESTED_QUESTIONS }: AssistantFooterProps) {
  const [expanded, setExpanded] = useState(false)
  const [turns, setTurns] = useState<ChatTurn[]>(() => loadCurrentTurns())
  const [sessions, setSessions] = useState<ChatSession[]>(() => loadSessions())
  const [question, setQuestion] = useState('')
  const [asking, setAsking] = useState(false)
  const [available, setAvailable] = useState<boolean | null>(null)

  const inputRef = useRef<HTMLTextAreaElement>(null)

  // Feature-detection reads GET /api/health's `capabilities` list. It does
  // NOT probe /api/ask -- the console used to POST an empty question here,
  // the service correctly answered 422, and the console read that as
  // "endpoint missing" and disabled the assistant against a working
  // backend. Capabilities describe the build, not the run, so this runs
  // once per mount rather than per runId.
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
    if (!expanded) return undefined
    function onKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key === 'Escape') {
        event.preventDefault()
        setExpanded(false)
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [expanded])

  async function submit(text: string) {
    const trimmed = text.trim()
    if (!trimmed || asking) return
    setQuestion('')
    // Asking is what expands the footer: the answer has nowhere to land in
    // the slim bar, and a question typed there is a request to see one.
    setExpanded(true)
    setAsking(true)
    // askTurn carries the capped prior turns as `history` and does the
    // failure mapping once. The run id the console loaded at startup goes
    // stale while the service keeps sweeping, and the 404 that produces
    // names the missing RUN, not a missing route -- askTurn retries that
    // against the latest run rather than reporting it, and
    // `endpointMissing` is left for a 404 that genuinely means there is no
    // such route. A 422, a 500 or a timeout is one question that failed
    // and leaves the composer enabled to retry.
    const outcome = await askTurn(runId, trimmed, turns)
    setAsking(false)
    if (outcome.endpointMissing) setAvailable(false)
    const next = [...turns, outcome.turn].slice(-MAX_TURNS)
    saveCurrentTurns(next)
    setTurns(next)
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

  function toggleExpanded() {
    const next = !expanded
    setExpanded(next)
    if (next) inputRef.current?.focus()
  }

  return (
    <div className={`assistant-footer${expanded ? ' assistant-footer--expanded' : ''}`}>
      {expanded && (
        <div className="assistant-footer__panel" role="region" aria-label="Mobility Intelligence assistant">
          <div className="assistant-footer__column">
            <ChatConversation
              turns={turns}
              sessions={sessions}
              asking={asking}
              available={available}
              suggestedQuestions={suggestedQuestions}
              onAsk={submit}
              onNewChat={onNewChat}
              onResume={onResume}
            />
          </div>
        </div>
      )}

      <form
        className="assistant-footer__bar"
        onSubmit={(event) => {
          event.preventDefault()
          submit(question)
        }}
      >
        <div className="assistant-footer__column assistant-footer__row">
          <label className="field__label assistant-footer__label" htmlFor="assistant-footer-input">
            Ask about this run
          </label>
          <textarea
            id="assistant-footer-input"
            className="assistant-footer__input"
            ref={inputRef}
            rows={1}
            value={question}
            disabled={available === false}
            placeholder={
              available === false ? 'Why did on-time fall this week?' : 'Ask about this run… "Why did on-time fall?"'
            }
            onChange={(event) => setQuestion(event.target.value)}
            onKeyDown={onComposerKeyDown}
          />
          <Button type="submit" busy={asking} disabled={available === false || !question.trim()}>
            Send
          </Button>
          <Button
            variant="ghost"
            size="sm"
            aria-expanded={expanded}
            aria-controls="assistant-footer-input"
            onClick={toggleExpanded}
          >
            {expanded ? 'Collapse' : 'Expand'}
          </Button>
        </div>
        {available === false && (
          <p className="assistant-footer__helper">Interrogation lands with the tools — coming</p>
        )}
      </form>
    </div>
  )
}
