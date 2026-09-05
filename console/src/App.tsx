import { useCallback, useEffect, useState } from 'react'
import { Navigate, NavLink, Route, Routes } from 'react-router-dom'
import './App.css'
import { getCost, getFeedHealth, getLatestFindings, sweepNow } from './api/client.ts'
import type { Cost, FeedHealth, Finding } from './api/types.ts'
import { Button } from './components/Button.tsx'
import { Legend } from './components/Legend.tsx'
import { BriefPage } from './pages/BriefPage.tsx'
import { CostPage } from './pages/CostPage.tsx'
import { FindingsPage } from './pages/FindingsPage.tsx'
import { HealthPage } from './pages/HealthPage.tsx'

interface RunState {
  runId: string
  windowLabel: string
  findings: Finding[]
}

// Vite's dev server serves an SPA fallback automatically (any unknown path
// resolves to index.html), so client-side routes work out of the box in
// `npm run dev`. A production static host does NOT do this by default --
// deploying this build needs a rewrite rule sending every path to
// /index.html (e.g. CloudFront's custom error response, or an S3 website
// redirect rule), or a deep link like /brief will 404 at the edge.
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
        <Legend />
        <Button onClick={sweepNowAndReload} busy={sweeping}>
          Sweep now
        </Button>
      </header>

      <nav aria-label="Primary" className="primary-nav">
        <NavLink
          to="/"
          end
          className={({ isActive }) => `primary-nav__link${isActive ? ' primary-nav__link--active' : ''}`}
        >
          Findings
        </NavLink>
        <NavLink
          to="/brief"
          className={({ isActive }) => `primary-nav__link${isActive ? ' primary-nav__link--active' : ''}`}
        >
          Brief
        </NavLink>
        <NavLink
          to="/health"
          className={({ isActive }) => `primary-nav__link${isActive ? ' primary-nav__link--active' : ''}`}
        >
          Feed health
        </NavLink>
        <NavLink
          to="/cost"
          className={({ isActive }) => `primary-nav__link${isActive ? ' primary-nav__link--active' : ''}`}
        >
          Cost
        </NavLink>
      </nav>

      {loading && <p className="console__status">Loading…</p>}
      {error && <p className="console__status console__status--error">{error}</p>}

      {!loading && !error && (
        <main className="console__main">
          <Routes>
            <Route path="/" element={<FindingsPage cost={cost} findings={run?.findings ?? []} />} />
            <Route path="/brief" element={run && <BriefPage runId={run.runId} />} />
            <Route path="/health" element={<HealthPage feeds={feeds ?? []} />} />
            <Route path="/cost" element={cost && <CostPage cost={cost} />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
      )}
    </div>
  )
}

export default App
