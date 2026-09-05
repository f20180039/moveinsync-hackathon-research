import { useState } from 'react'
import { dispatch, getBrief, getLatestFindings, sweepNow } from '../api/client.ts'
import { label } from '../api/labels.ts'
import type { Audience, Brief, DispatchAudienceResult, Finding, SweepWindow } from '../api/types.ts'
import { AUDIENCES } from '../api/types.ts'
import { Button } from './Button.tsx'
import { FindingsList } from './FindingsList.tsx'
import { KpiRow } from './KpiRow.tsx'
import { Select } from './Select.tsx'

export interface ReviewReportProps {
  window: SweepWindow
  title: string
}

interface RunResult {
  runId: string
  windowLabel: string
  windowKind: SweepWindow | null
  findings: Finding[]
}

// Shared by /reports/weekly and /reports/monthly -- "Run <window> review"
// sweeps that window, then shows the run's KPI row, top findings, and a
// brief (with Copy for leadership + Dispatch) for a chosen audience.
export function ReviewReport({ window, title }: ReviewReportProps) {
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [run, setRun] = useState<RunResult | null>(null)

  const [audience, setAudience] = useState<Audience>(AUDIENCES[0])
  const [brief, setBrief] = useState<Brief | null>(null)
  const [briefLoading, setBriefLoading] = useState(false)
  const [copied, setCopied] = useState(false)

  const [dispatching, setDispatching] = useState(false)
  const [dispatchResult, setDispatchResult] = useState<DispatchAudienceResult[] | null>(null)

  async function runReview() {
    setRunning(true)
    setError(null)
    setBrief(null)
    setDispatchResult(null)
    try {
      await sweepNow(window)
      const findingsRes = await getLatestFindings()
      setRun({
        runId: findingsRes.runId,
        windowLabel: findingsRes.windowLabel,
        windowKind: findingsRes.windowKind ?? null,
        findings: findingsRes.findings,
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setRunning(false)
    }
  }

  async function loadBrief() {
    if (!run) return
    setBriefLoading(true)
    setCopied(false)
    try {
      const result = await getBrief(run.runId, audience)
      setBrief(result)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBriefLoading(false)
    }
  }

  async function dispatchBrief() {
    if (!run) return
    setDispatching(true)
    try {
      const result = await dispatch(run.runId)
      setDispatchResult(result.dispatched)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setDispatching(false)
    }
  }

  function copyForLeadership() {
    if (!brief) return
    // navigator.clipboard is not present in jsdom / some embedded browsers
    // -- guarded so a click never throws in tests or a locked-down runtime.
    if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
      navigator.clipboard
        .writeText(brief.brief)
        .then(() => setCopied(true))
        .catch(() => {})
    }
  }

  const paramNotHonoured = run && run.windowKind !== null && run.windowKind !== window

  return (
    <section>
      <h1 className="page-heading">{title}</h1>

      <Button onClick={runReview} busy={running}>
        Run {window} review
      </Button>

      {error && <p className="report-page__error">{error}</p>}

      {run && (
        <>
          <p className="report-page__window">
            {run.windowKind ? label('windowKind', run.windowKind) : 'Window'} · {run.windowLabel} · run{' '}
            {run.runId}
          </p>

          {paramNotHonoured && (
            <p className="report-page__note">
              This service returned a "{run.windowKind}" window; the "{window}" request may not be honoured by
              this service yet.
            </p>
          )}
          {run.windowKind === null && (
            <p className="report-page__note">
              This service response has no windowKind field yet -- can't confirm whether the {window} request was
              honoured.
            </p>
          )}

          <KpiRow findings={run.findings} />

          <section>
            <h2 className="panel-heading">Top findings</h2>
            <FindingsList findings={run.findings.slice(0, 5)} />
          </section>

          <section className="report-page__brief">
            <h2 className="panel-heading">Brief</h2>
            <div className="brief-preview__controls">
              <Select
                label="Audience"
                value={audience}
                onChange={setAudience}
                options={AUDIENCES.map((a) => ({ value: a, label: label('audience', a) }))}
              />
              <Button onClick={loadBrief} busy={briefLoading}>
                Preview brief
              </Button>
              {brief && (
                <Button variant="secondary" onClick={copyForLeadership}>
                  {copied ? 'Copied' : 'Copy for leadership'}
                </Button>
              )}
              <Button variant="primary" onClick={dispatchBrief} busy={dispatching}>
                Dispatch
              </Button>
            </div>

            {brief && (
              <>
                <span className="brief-preview__source">Source: {label('source', brief.source)}</span>
                <pre className="brief-preview__text">{brief.brief}</pre>
              </>
            )}

            {dispatchResult && (
              <ul className="brief-preview__dispatch-results">
                {dispatchResult.map((result) => (
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
          </section>
        </>
      )}
    </section>
  )
}
