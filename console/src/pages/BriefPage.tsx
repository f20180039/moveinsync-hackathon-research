import { useEffect, useState } from 'react'
import { dispatch, getBrief, getDispatchLog } from '../api/client.ts'
import { label } from '../api/labels.ts'
import type { Audience, Brief, DispatchAudienceResult } from '../api/types.ts'
import { AUDIENCES } from '../api/types.ts'
import { Button } from '../components/Button.tsx'
import { Select } from '../components/Select.tsx'

export function BriefPage({ runId }: { runId: string }) {
  const [audience, setAudience] = useState<Audience>(AUDIENCES[0])
  const [brief, setBrief] = useState<Brief | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [dispatched, setDispatched] = useState<DispatchAudienceResult[] | null>(null)
  const [dispatching, setDispatching] = useState(false)
  const [log, setLog] = useState<DispatchAudienceResult[] | null>(null)

  useEffect(() => {
    let ignore = false
    // The dispatch log is not part of the frozen contract -- treat a
    // rejection (404, or anything else) as "no log available", never as a
    // page-level error.
    // oxlint-disable-next-line react/set-state-in-effect
    getDispatchLog()
      .then((entries) => {
        if (!ignore) setLog(entries)
      })
      .catch(() => {
        /* Optional endpoint absent -- leave the section hidden. */
      })
    return () => {
      ignore = true
    }
  }, [])

  async function loadBrief() {
    setLoading(true)
    setError(null)
    setDispatched(null)
    try {
      const result = await getBrief(runId, audience)
      setBrief(result)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }

  async function sendDispatch() {
    setDispatching(true)
    setError(null)
    try {
      const result = await dispatch(runId)
      setDispatched(result.dispatched)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setDispatching(false)
    }
  }

  return (
    <section>

      <div className="brief-preview__controls">
        <Select
          label="Audience"
          value={audience}
          onChange={setAudience}
          options={AUDIENCES.map((a) => ({ value: a, label: label('audience', a) }))}
        />
        <Button onClick={loadBrief} busy={loading}>
          Preview brief
        </Button>
        <Button variant="primary" onClick={sendDispatch} busy={dispatching}>
          Dispatch
        </Button>
        {brief && <span className="brief-preview__source">Source: {label('source', brief.source)}</span>}
      </div>

      {error && <p className="brief-preview__error">{error}</p>}

      {brief && <pre className="brief-preview__text">{brief.brief}</pre>}

      {dispatched && (
        <ul className="brief-preview__dispatch-results">
          {dispatched.map((result) => (
            <li key={result.audience}>
              <strong>{label('audience', result.audience)}</strong>
              <ul>
                {result.channels.map((channel) => (
                  <li key={channel.channel}>
                    {label('channel', channel.channel)} · {channel.delivered ? 'delivered' : channel.detail}
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      )}

      {log && log.length > 0 && (
        <div className="brief-preview__log">
          <h2 className="panel-heading">Dispatch log</h2>
          <ul className="brief-preview__dispatch-results">
            {log.map((result, index) => (
              // The log has no stable id of its own; audience + position is
              // stable enough for a small, append-only list like this.
              <li key={`${result.audience}-${index}`}>
                <strong>{label('audience', result.audience)}</strong>
                <ul>
                  {result.channels.map((channel) => (
                    <li key={channel.channel}>
                      {label('channel', channel.channel)} · {channel.delivered ? 'delivered' : channel.detail}
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}
