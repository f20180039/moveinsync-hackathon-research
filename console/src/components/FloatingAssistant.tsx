import { useEffect, useRef, useState } from 'react'
import { ApiError, ask, getCapabilities, hasCapability } from '../api/client.ts'
import { DEFAULT_SUGGESTED_QUESTIONS } from '../api/insights.ts'
import type { AskResponse } from '../api/types.ts'
import { Button } from './Button.tsx'

const STORAGE_KEY = 'signal-desk:assistant-conversation'
// A long-running session shouldn't grow this file without bound -- the
// oldest exchanges fall off once there are more than this many.
const MAX_EXCHANGES = 50

interface Exchange {
  id: string
  question: string
  // Present on a real reply from the service (including a withheld one --
  // withheld is carried on the response itself, not a separate error).
  response: AskResponse | null
  // Set only when the request itself failed (network error, or the
  // endpoint isn't available) -- distinct from a withheld answer, which is
  // a normal, non-error response the assistant chose not to answer.
  error: string | null
}

// localStorage can throw (private browsing, a full quota, storage
// disabled) -- every read/write is guarded so the conversation degrades to
// "doesn't persist this session" rather than crashing the panel.
function loadHistory(): Exchange[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

function saveHistory(history: Exchange[]): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(history.slice(-MAX_EXCHANGES)))
  } catch {
    // Nothing to do -- the conversation still works for this render, it
    // just won't survive a reload.
  }
}

function makeId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`
}

export interface FloatingAssistantProps {
  runId: string
  /** Overridable per role (Stage 7's persona switch swaps the second chip
   * for the Facilities head role) -- defaults to the standard four. */
  suggestedQuestions?: string[]
}

function TraceView({ trace }: { trace: AskResponse['trace'] }) {
  if (!Array.isArray(trace) || trace.length === 0) return null
  return (
    <pre className="assistant-panel__trace">{JSON.stringify(trace, null, 2)}</pre>
  )
}

function ExchangeView({ exchange }: { exchange: Exchange }) {
  const [traceOpen, setTraceOpen] = useState(false)
  const { response, error } = exchange

  return (
    <div className="assistant-panel__exchange">
      <p className="assistant-panel__question">{exchange.question}</p>

      {error && <p className="assistant-panel__error">{error}</p>}

      {response && response.withheld && (
        <div className="assistant-panel__withheld">
          <p>{response.reason ?? 'The assistant withheld an answer for this question.'}</p>
        </div>
      )}

      {response && !response.withheld && <p className="assistant-panel__reply">{response.answer}</p>}

      {response && Array.isArray(response.trace) && response.trace.length > 0 && (
        <>
          <Button variant="ghost" size="sm" aria-expanded={traceOpen} onClick={() => setTraceOpen((v) => !v)}>
            {traceOpen ? 'Hide trace' : 'Show trace'}
          </Button>
          {traceOpen && <TraceView trace={response.trace} />}
        </>
      )}
    </div>
  )
}

// A fixed bottom-right launcher/panel, replacing the old inline AskBar --
// mounted once at the App shell level (not per-page), so the conversation
// survives navigating between routes without being torn down. Persisted to
// localStorage too, so it survives a reload; capped at MAX_EXCHANGES so it
// can't grow without bound.
//
// Deliberately not a native <dialog>/showModal() (see Legend for that
// pattern) -- aria-modal="false" means the rest of the page must stay
// operable while this is open, which a native modal dialog's backdrop and
// inert background would break.
export function FloatingAssistant({ runId, suggestedQuestions = DEFAULT_SUGGESTED_QUESTIONS }: FloatingAssistantProps) {
  const [open, setOpen] = useState(false)
  const [available, setAvailable] = useState<boolean | null>(null)
  const [question, setQuestion] = useState('')
  const [asking, setAsking] = useState(false)
  const [history, setHistory] = useState<Exchange[]>(() => loadHistory())

  const launcherRef = useRef<HTMLButtonElement>(null)
  const previouslyFocusedRef = useRef<HTMLElement | null>(null)
  const historyRef = useRef<HTMLDivElement>(null)

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
    if (!open) return undefined
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.preventDefault()
        close()
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  useEffect(() => {
    if (open && historyRef.current) {
      historyRef.current.scrollTop = historyRef.current.scrollHeight
    }
  }, [open, history])

  function openPanel() {
    previouslyFocusedRef.current = document.activeElement as HTMLElement | null
    setOpen(true)
  }

  function close() {
    setOpen(false)
    ;(previouslyFocusedRef.current ?? launcherRef.current)?.focus()
  }

  async function submit(text: string) {
    const trimmed = text.trim()
    if (!trimmed) return
    setQuestion('')
    setAsking(true)
    let exchange: Exchange
    try {
      exchange = { id: makeId(), question: trimmed, response: await ask(runId, trimmed), error: null }
    } catch (err) {
      // Only a 404 means this build has no /api/ask; a 422, a 500 or a
      // timeout is one question that failed, so the input stays enabled
      // and the user can retry.
      if (err instanceof ApiError && err.status === 404) setAvailable(false)
      exchange = {
        id: makeId(),
        question: trimmed,
        response: null,
        error:
          err instanceof ApiError && err.status === 404
            ? 'This build does not serve the assistant endpoint.'
            : 'Could not reach the assistant -- try again in a moment.',
      }
    } finally {
      setAsking(false)
    }
    setHistory((prev) => {
      const next = [...prev, exchange].slice(-MAX_EXCHANGES)
      saveHistory(next)
      return next
    })
  }

  return (
    <div className="assistant">
      <Button
        ref={launcherRef}
        className="assistant-launcher"
        aria-expanded={open}
        aria-label={open ? 'Close Mobility Intelligence assistant' : 'Open Mobility Intelligence assistant'}
        onClick={() => (open ? close() : openPanel())}
      >
        <span aria-hidden="true">{open ? '✕' : '💬'}</span>
      </Button>

      {open && (
        <div className="assistant-panel" role="dialog" aria-modal="false" aria-label="Mobility Intelligence assistant">
          <div className="assistant-panel__header">
            <h2 className="assistant-panel__title">Mobility Intelligence</h2>
            <Button variant="ghost" size="sm" onClick={close}>
              Close
            </Button>
          </div>

          {/* Two columns: the starter questions down the left, the
              conversation on the right. Below the width where both fit,
              CSS reflows this same markup to a capped, scrollable row
              above the conversation -- no second render path, and no
              horizontal scroll at any width. */}
          <div className="assistant-panel__body">
            <div className="assistant-panel__suggestions">
              <h3 className="assistant-panel__suggestions-title">Suggested</h3>
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

            <div className="assistant-panel__history" ref={historyRef}>
              {history.length === 0 ? (
                <p className="assistant-panel__empty">Ask a question about this window's findings.</p>
              ) : (
                history.map((exchange) => <ExchangeView key={exchange.id} exchange={exchange} />)
              )}
            </div>
          </div>

          <form
            className="assistant-panel__form"
            onSubmit={(event) => {
              event.preventDefault()
              submit(question)
            }}
          >
            <label className="field__label" htmlFor="assistant-input">
              Ask a question about this window's findings
            </label>
            <div className="assistant-panel__row">
              <input
                id="assistant-input"
                className="assistant-panel__input"
                type="text"
                value={question}
                disabled={available === false}
                placeholder={
                  available === false
                    ? 'Why did on-time fall this week?'
                    : 'Ask Mobility Intelligence… "Why did on-time fall this week?"'
                }
                onChange={(event) => setQuestion(event.target.value)}
              />
              <Button type="submit" busy={asking} disabled={available === false || !question.trim()}>
                Send
              </Button>
            </div>
            {available === false && (
              <p className="assistant-panel__helper">Interrogation lands with the tools — coming</p>
            )}
          </form>
        </div>
      )}
    </div>
  )
}
