import { useCallback, useEffect, useState } from 'react'
import './App.css'
import { getCost, getFeedHealth, getLatestFindings, sweepNow } from './api/client.ts'
import type { Cost, FeedHealth, Finding } from './api/types.ts'
import { BriefPreview } from './components/BriefPreview.tsx'
import { Button } from './components/Button.tsx'
import { CostMeter } from './components/CostMeter.tsx'
import { FeedHealthStrip } from './components/FeedHealthStrip.tsx'
import { FindingsList } from './components/FindingsList.tsx'
import { Legend } from './components/Legend.tsx'

interface RunState {
  runId: string
  windowLabel: string
  findings: Finding[]
}

function App() {
  const [run, setRun] = useState<RunState | null>(null)
  const [feeds, setFeeds] = useState<FeedHealth[] | null>(null)
  const [cost, setCost] = useState<Cost | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [sweeping, setSweeping] = useState(false)

  // `ignore` guards against setting state from a load that started before an
  // unmount (or before "Sweep now" kicked off a fresher one) resolves after.
  const load = useCallback(async (ignore: { current: boolean } = { current: false }) => {
    setLoading(true)
    setError(null)
    try {
      const [findingsRes, feedsRes, costRes] = await Promise.all([
        getLatestFindings(),
        getFeedHealth(),
        getCost(),
      ])
      if (ignore.current) return
      setRun({
        runId: findingsRes.runId,
        windowLabel: findingsRes.windowLabel,
        findings: findingsRes.findings,
      })
      setFeeds(feedsRes)
      setCost(costRes)
    } catch (err) {
      if (ignore.current) return
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      if (!ignore.current) setLoading(false)
    }
  }, [])

  // Fetches each route exactly once per mount. No interval, no retry on
  // failure -- an error renders the error state and waits for the operator
  // to press "Sweep now" rather than hammering the API on its own.
  useEffect(() => {
    const ignore = { current: false }
    // This *is* the fetch-on-mount -- the "external system" being
    // synchronized -- so there is no render-time value to derive it from.
    // oxlint-disable-next-line react/set-state-in-effect
    load(ignore)
    return () => {
      ignore.current = true
    }
  }, [load])

  async function sweepNowAndReload() {
    setSweeping(true)
    try {
      await sweepNow()
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setSweeping(false)
    }
  }

  return (
    <div className="console">
      <header className="console__header">
        <h1>Signal Desk</h1>
        {run && (
          <span className="console__run-meta">
            {run.windowLabel} · run {run.runId}
          </span>
        )}
        <Button onClick={sweepNowAndReload} busy={sweeping}>
          Sweep now
        </Button>
      </header>

      {loading && <p className="console__status">Loading…</p>}
      {error && <p className="console__status console__status--error">{error}</p>}

      {!loading && !error && (
        <main className="console__main">
          <Legend />

          {/* Control strip: brief controls + cost meter, both visible
              without scrolling; the brief text panel spans full width
              underneath. Order top -> bottom matters for the DOM-order
              test below -- this must come before the findings section. */}
          <div className="control-strip" data-testid="control-strip">
            {run && <BriefPreview runId={run.runId} />}
            {cost && (
              <div className="control-strip__cost">
                <h2 className="panel-heading">Cost</h2>
                <CostMeter cost={cost} />
              </div>
            )}
          </div>

          {feeds && <FeedHealthStrip feeds={feeds} />}

          {run && (
            <section className="findings-section" data-testid="findings-section">
              <h2 className="panel-heading">Findings</h2>
              <FindingsList findings={run.findings} />
            </section>
          )}
        </main>
      )}
    </div>
  )
}

export default App
