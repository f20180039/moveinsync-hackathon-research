import { useEffect, useState } from 'react'
import { dispatch, getBrief, getLatestFindings, getRunFindings, sweepNow } from '../api/client.ts'
import { label } from '../api/labels.ts'
import type { Audience, Brief, DispatchAudienceResult, Finding, SweepWindow } from '../api/types.ts'
import { AUDIENCES } from '../api/types.ts'
import { Button } from './Button.tsx'
import { FindingsList } from './FindingsList.tsx'
import { KpiRow } from './KpiRow.tsx'
import { ReviewSummary } from './ReviewSummary.tsx'
import { Select } from './Select.tsx'

export interface ReviewReportProps {
  window: SweepWindow
  title: string
}

// Where the findings on screen came from. "latest" is the run the service
// already has (loaded on mount so the page is a report, not a button);
// "sweep" is a run this page asked for with its own window. The two are
// labelled differently on screen because they are not the same claim.
type RunSource = 'latest' | 'sweep'

interface RunResult {
  runId: string
  windowLabel: string
  windowKind: SweepWindow | null
  findings: Finding[]
  source: RunSource
}

// Shared by /reports/weekly and /reports/monthly.
//
// It loads the service's latest run on mount and renders it as an actual
// report -- verdict mix, per-metric summary, worst slices, recurring
// findings -- so the page says something the moment it opens. "Run
// <window> review" then sweeps *this page's* window and replaces the
// report with that run. That ordering matters: POST /api/sweep is the
// slowest and least reliable call in the product (it re-runs the whole
// analysis server-side and can fail outright), and a review page whose
// entire content sat behind it showed a blank screen whenever it did.
// A failed sweep now leaves the mounted report standing and says the
// window was not re-run, instead of emptying the page.
export function ReviewReport({ window, title }: ReviewReportProps) {
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [run, setRun] = useState<RunResult | null>(null)

  const [audience, setAudience] = useState<Audience>(AUDIENCES[0])
  const [brief, setBrief] = useState<Brief | null>(null)
  const [briefLoading, setBriefLoading] = useState(false)
  const [copied, setCopied] = useState(false)
  const [copyUnavailable, setCopyUnavailable] = useState(false)

  const [dispatching, setDispatching] = useState(false)
  const [dispatchResult, setDispatchResult] = useState<DispatchAudienceResult[] | null>(null)

  const [loading, setLoading] = useState(true)

  // Mount load. Deliberately silent on failure: this is the fallback that
  // makes the page non-empty, so if it cannot run there is simply nothing
  // to show yet and the Run button is still there. A page-level error here
  // would be reporting a request the user never asked for.
  useEffect(() => {
    let cancelled = false
    getLatestFindings()
      .then((res) => {
        if (cancelled) return
        setRun({
          runId: res.runId,
          windowLabel: res.windowLabel,
          windowKind: res.windowKind ?? null,
          findings: res.findings,
          source: 'latest',
        })
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  async function runReview() {
    setRunning(true)
    setError(null)
    setBrief(null)
    setDispatchResult(null)
    try {
      const sweepResult = await sweepNow(window)
      // Use the run the sweep just created, not whatever /latest happens
      // to point at right now -- the TopBar's Sweep-now, or a second tab,
      // could otherwise swap the run out from under this one between the
      // two requests.
      const findingsRes = await getRunFindings(sweepResult.runId)
      setRun({
        runId: findingsRes.runId,
        windowLabel: findingsRes.windowLabel,
        windowKind: findingsRes.windowKind ?? null,
        findings: findingsRes.findings,
        source: 'sweep',
      })
    } catch (err) {
      // The report already on screen stays on screen -- it is a real run,
      // just not the one the user asked to re-sweep, and the note under
      // the button says exactly that.
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setRunning(false)
    }
  }

  async function loadBrief() {
    if (!run) return
    setBriefLoading(true)
    setCopied(false)
    setCopyUnavailable(false)
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
    // navigator.clipboard is not present in every embedded browser or
    // locked-down runtime -- guarded so a click never throws, and the
    // user is told plainly rather than the button just doing nothing.
    if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
      navigator.clipboard
        .writeText(brief.brief)
        .then(() => setCopied(true))
        .catch(() => setCopyUnavailable(true))
    } else {
      setCopyUnavailable(true)
    }
  }

  // Only meaningful about a run this page asked for: the mount-loaded
  // latest run was never asked to be this page's window, so a mismatch
  // there is not the service ignoring a parameter.
  const sweptRun = run?.source === 'sweep' ? run : null
  const paramNotHonoured = sweptRun && sweptRun.windowKind !== null && sweptRun.windowKind !== window

  return (
    <section>
      <h2 className="page-heading">{title}</h2>

      <Button onClick={runReview} busy={running}>
        Run {window} review
      </Button>

      {error && (
        <p className="report-page__error">
          {run ? `Could not re-run the ${window} window (${error}) — showing the service's latest run instead.` : error}
        </p>
      )}

      {!run && loading && <p className="report-page__note">Loading the latest run…</p>}
      {!run && !loading && (
        <p className="report-page__note">
          No run to report on yet — run the {label('windowKind', window)} review to produce one.
        </p>
      )}

      {run && (
        <>
          <p className="report-page__window">
            {run.windowKind ? label('windowKind', run.windowKind) : 'Window'} · {run.windowLabel} · run{' '}
            {run.runId}
          </p>

          {run.source === 'latest' && (
            <p className="report-page__note">
              This is the service's latest run, loaded when the page opened — not a sweep of this page's window. Run
              the review to re-sweep it.
            </p>
          )}

          {paramNotHonoured && (
            <p className="report-page__note">
              This service returned a "{label('windowKind', sweptRun?.windowKind as string)}" window; the "
              {label('windowKind', window)}" request may not be honoured by this service yet.
            </p>
          )}
          {sweptRun && sweptRun.windowKind === null && (
            <p className="report-page__note">
              This service response has no windowKind field yet -- can't confirm whether the{' '}
              {label('windowKind', window)} request was honoured.
            </p>
          )}

          <KpiRow findings={run.findings} />

          <ReviewSummary findings={run.findings} />

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

            {copyUnavailable && (
              <p className="report-page__note">Copy not available in this browser -- select the text above instead.</p>
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
