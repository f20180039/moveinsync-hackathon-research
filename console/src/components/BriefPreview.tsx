import { useState } from 'react'
import { dispatch, getBrief } from '../api/client.ts'
import type { Audience, Brief, DispatchAudienceResult } from '../api/types.ts'
import { AUDIENCES } from '../api/types.ts'

export function BriefPreview({ runId }: { runId: string }) {
  const [audience, setAudience] = useState<Audience>(AUDIENCES[0])
  const [brief, setBrief] = useState<Brief | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [dispatched, setDispatched] = useState<DispatchAudienceResult[] | null>(null)
  const [dispatching, setDispatching] = useState(false)

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
    <div className="brief-preview">
      <div className="brief-preview__controls">
        <label htmlFor="brief-audience">Audience</label>
        <select
          id="brief-audience"
          value={audience}
          onChange={(event) => setAudience(event.target.value as Audience)}
        >
          {AUDIENCES.map((a) => (
            <option key={a} value={a}>
              {a}
            </option>
          ))}
        </select>
        <button type="button" onClick={loadBrief} disabled={loading}>
          {loading ? 'Loading brief…' : 'Preview brief'}
        </button>
        <button type="button" onClick={sendDispatch} disabled={dispatching}>
          {dispatching ? 'Dispatching…' : 'Dispatch'}
        </button>
      </div>

      {error && <p className="brief-preview__error">{error}</p>}

      {brief && (
        <div className="brief-preview__brief">
          <span className="brief-preview__source">source: {brief.source}</span>
          <pre className="brief-preview__text">{brief.brief}</pre>
        </div>
      )}

      {dispatched && (
        <ul className="brief-preview__dispatch-results">
          {dispatched.map((result) => (
            <li key={result.audience}>
              <strong>{result.audience}</strong>
              <ul>
                {result.channels.map((channel) => (
                  <li key={channel.channel}>
                    {channel.channel} · {channel.delivered ? 'delivered' : channel.detail}
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
