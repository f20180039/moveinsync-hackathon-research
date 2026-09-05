import { useEffect, useState } from 'react'
import { ApiError, ask, getCapabilities, hasCapability } from '../api/client.ts'
import type { AskResponse } from '../api/types.ts'
import { Button } from './Button.tsx'
import { Card } from './Card.tsx'

const SUGGESTED_QUESTIONS = [
  'Why is OTA low this week?',
  'Which vendor is underperforming?',
  'Where are no-shows concentrated?',
  'What changed vs last week?',
]

export interface AskBarProps {
  runId: string
}

// "Ask Mobility Intelligence…" -- superseded by FloatingAssistant and kept
// only until it can be deleted. Feature-detects off GET /api/health's
// `capabilities` list, never by probing /api/ask with a question it knows
// is invalid: the service answers 422 to that and the old code read the
// 422 as "endpoint missing", disabling the feature against a live backend.
export function AskBar({ runId }: AskBarProps) {
  const [available, setAvailable] = useState<boolean | null>(null)
  const [question, setQuestion] = useState('')
  const [asking, setAsking] = useState(false)
  const [answer, setAnswer] = useState<AskResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [traceOpen, setTraceOpen] = useState(false)

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

  async function submit(text: string) {
    if (!text.trim()) return
    setAsking(true)
    setAnswer(null)
    setError(null)
    try {
      setAnswer(await ask(runId, text))
    } catch (err) {
      // Only a 404 disables the feature; a 422/500/timeout is one failed
      // question and leaves the input usable.
      if (err instanceof ApiError && err.status === 404) setAvailable(false)
      setError(
        err instanceof ApiError && err.status === 404
          ? 'This build does not serve the assistant endpoint.'
          : 'Could not reach the assistant -- try again in a moment.',
      )
    } finally {
      setAsking(false)
    }
  }

  return (
    <Card className="ask-bar">
      <h2 className="panel-heading">Ask Mobility Intelligence</h2>

      <form
        className="ask-bar__form"
        onSubmit={(event) => {
          event.preventDefault()
          submit(question)
        }}
      >
        <label className="field__label" htmlFor="ask-bar-input">
          Ask a question about this window's findings
        </label>
        <div className="ask-bar__row">
          <input
            id="ask-bar-input"
            className="ask-bar__input"
            type="text"
            value={question}
            disabled={available === false}
            placeholder={
              available === false
                ? "Why did OTA fall this week?"
                : "Ask Mobility Intelligence… \"Why did OTA fall this week?\""
            }
            onChange={(event) => setQuestion(event.target.value)}
          />
          <Button type="submit" busy={asking} disabled={available === false || !question.trim()}>
            Send
          </Button>
        </div>
        {available === false && (
          <p className="ask-bar__helper">Interrogation lands with the tools — coming</p>
        )}
      </form>

      <div className="ask-bar__chips">
        {SUGGESTED_QUESTIONS.map((suggestion) => (
          <Button
            key={suggestion}
            variant="ghost"
            size="sm"
            disabled={available === false}
            onClick={() => {
              setQuestion(suggestion)
              submit(suggestion)
            }}
          >
            {suggestion}
          </Button>
        ))}
      </div>

      {error && <p className="ask-bar__error">{error}</p>}

      {answer && (
        <div className="ask-bar__answer">
          <p>{answer.answer}</p>
          {Array.isArray(answer.trace) && answer.trace.length > 0 && (
            <>
              <Button variant="ghost" size="sm" aria-expanded={traceOpen} onClick={() => setTraceOpen((v) => !v)}>
                {traceOpen ? 'Hide trace' : 'Show trace'}
              </Button>
              {traceOpen && (
                <pre className="ask-bar__trace">{JSON.stringify(answer.trace, null, 2)}</pre>
              )}
            </>
          )}
        </div>
      )}
    </Card>
  )
}
