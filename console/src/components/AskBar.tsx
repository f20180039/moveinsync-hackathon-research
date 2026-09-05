import { useEffect, useState } from 'react'
import { ask } from '../api/client.ts'
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

// "Ask Mobility Intelligence…" -- POST /api/ask is not live yet, so this
// feature-detects: a first probe call decides whether to show the real
// input or the disabled, honest placeholder. Never silently pretends the
// feature works when the endpoint 404s.
export function AskBar({ runId }: AskBarProps) {
  const [available, setAvailable] = useState<boolean | null>(null)
  const [question, setQuestion] = useState('')
  const [asking, setAsking] = useState(false)
  const [answer, setAnswer] = useState<AskResponse | null>(null)
  const [traceOpen, setTraceOpen] = useState(false)

  useEffect(() => {
    let ignore = false
    // A cheap probe with an empty question just to learn whether the route
    // exists at all -- feature-detection, not a real question.
    // oxlint-disable-next-line react/set-state-in-effect
    ask(runId, '').then((result) => {
      if (!ignore) setAvailable(result !== null)
    })
    return () => {
      ignore = true
    }
  }, [runId])

  async function submit(text: string) {
    if (!text.trim()) return
    setAsking(true)
    setAnswer(null)
    try {
      const result = await ask(runId, text)
      setAnswer(result)
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
