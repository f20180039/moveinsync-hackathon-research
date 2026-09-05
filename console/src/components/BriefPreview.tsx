import { useId, useState } from 'react'
import { dispatch, getBrief } from '../api/client.ts'
import type { Audience, Brief, DispatchAudienceResult } from '../api/types.ts'
import { AUDIENCES } from '../api/types.ts'
import { Button } from './Button.tsx'
import { Select } from './Select.tsx'

// Renders as a Fragment with two top-level pieces, deliberately -- the
// caller (App) places them in different cells of the control-strip grid:
// the controls (select, buttons, source tag) sit next to the CostMeter, and
// the brief TEXT renders in its own collapsible panel spanning the full
// width of the row underneath. A Fragment has no wrapper element, so both
// land as direct grid children.
export function BriefPreview({ runId }: { runId: string }) {
  const [audience, setAudience] = useState<Audience>(AUDIENCES[0])
  const [brief, setBrief] = useState<Brief | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [dispatched, setDispatched] = useState<DispatchAudienceResult[] | null>(null)
  const [dispatching, setDispatching] = useState(false)
  const [textOpen, setTextOpen] = useState(false)
  const textPanelId = useId()

  async function loadBrief() {
    setLoading(true)
    setError(null)
    setDispatched(null)
    try {
      const result = await getBrief(runId, audience)
      setBrief(result)
      setTextOpen(true) // open once a brief has been fetched
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
    <>
      <div className="control-strip__brief">
        <h2 className="panel-heading">Send a brief</h2>
        <div className="brief-preview__controls">
          <Select
            label="Audience"
            value={audience}
            onChange={setAudience}
            options={AUDIENCES.map((a) => ({ value: a, label: a }))}
          />
          <Button onClick={loadBrief} busy={loading}>
            Preview brief
          </Button>
          <Button variant="primary" onClick={sendDispatch} busy={dispatching}>
            Dispatch
          </Button>
          {brief && <span className="brief-preview__source">source: {brief.source}</span>}
        </div>

        {error && <p className="brief-preview__error">{error}</p>}

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

      {brief && (
        <div className="control-strip__brief-text">
          <div className="brief-preview__text-header">
            <span className="panel-heading">Brief text</span>
            <Button
              variant="ghost"
              size="sm"
              aria-expanded={textOpen}
              aria-controls={textPanelId}
              onClick={() => setTextOpen((value) => !value)}
            >
              {textOpen ? 'Hide brief' : 'Show brief'}
            </Button>
          </div>
          {textOpen && (
            <pre id={textPanelId} className="brief-preview__text">
              {brief.brief}
            </pre>
          )}
        </div>
      )}
    </>
  )
}
