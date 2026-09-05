import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import fixture from '../../../handoff/fake-findings.json'
import { ReviewReport } from './ReviewReport.tsx'

function jsonResponse(body: unknown) {
  return Promise.resolve({ ok: true, json: async () => body } as Response)
}

function notFound() {
  return Promise.resolve({ ok: false, status: 404, statusText: 'Not Found', text: async () => '' } as Response)
}

// The page loads the service's latest run on mount so it is a report and
// not a button. `latest` decides what that mount load gets: 'missing'
// (404) keeps the pre-existing tests below testing exactly the flow they
// always tested -- nothing on screen until Run review -- and 'present'
// exercises the mount load itself.
function mockFetch(windowKind: 'week' | 'month' | null, latest: 'missing' | 'present' = 'missing') {
  return vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.includes('/api/runs/latest/findings')) {
      if (latest === 'missing') return notFound()
      return jsonResponse({
        runId: fixture.runId,
        windowLabel: fixture.windowLabel,
        findings: fixture.findings,
        windowKind: 'week',
      })
    }
    if (url.includes('/api/sweep')) {
      return jsonResponse({ runId: fixture.runId, findingCount: fixture.findings.length })
    }
    // The findings fetch must ask for *this run's* findings (the runId
    // the sweep above just returned), not /latest -- a stray call to
    // /latest here would 404 against this mock and fail every test in
    // this file, which is exactly the point.
    if (url.includes(`/api/runs/${fixture.runId}/findings`)) {
      return jsonResponse({
        runId: fixture.runId,
        windowLabel: fixture.windowLabel,
        findings: fixture.findings,
        ...(windowKind ? { windowKind } : {}),
      })
    }
    if (url.includes('/brief')) {
      return jsonResponse({
        runId: fixture.runId,
        audience: 'TRANSPORT_MANAGER',
        brief: 'Weekly brief text.',
        source: 'template',
      })
    }
    if (url.includes('/api/dispatch/')) {
      return jsonResponse({ runId: fixture.runId, dispatched: [] })
    }
    void init
    return notFound()
  })
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('ReviewReport', () => {
  it('runs the review (POST /api/sweep?window=week) and shows the KPI row and top findings', async () => {
    const fetchMock = mockFetch('week')
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()

    render(<ReviewReport window="week" title="Weekly review" />)

    await user.click(screen.getByRole('button', { name: /run week review/i }))

    expect(await screen.findByText(new RegExp(fixture.windowLabel))).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'On-time arrival' })).toBeInTheDocument() // KPI row
    expect(screen.getAllByText(fixture.findings[0].metricLabel).length).toBeGreaterThan(0)

    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/api/sweep?window=week'), expect.anything())
  })

  it('fetches findings for the run the sweep just created, not /latest', async () => {
    // Deliberately different from anything else in this file's fixtures,
    // so a passing test can only mean the runId travelled from the sweep
    // response into the findings request -- not that it happened to
    // match some other constant.
    const sweptRunId = 'run-from-this-sweep-only'
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/api/runs/latest/findings')) return notFound()
      if (url.includes('/api/sweep')) {
        return jsonResponse({ runId: sweptRunId, findingCount: fixture.findings.length })
      }
      if (url.includes(`/api/runs/${sweptRunId}/findings`)) {
        return jsonResponse({
          runId: sweptRunId,
          windowLabel: fixture.windowLabel,
          findings: fixture.findings,
          windowKind: 'week',
        })
      }
      return notFound()
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()

    render(<ReviewReport window="week" title="Weekly review" />)
    const latestCallsBeforeSweep = fetchMock.mock.calls.filter(([input]) =>
      String(input).includes('/api/runs/latest/findings'),
    ).length

    await user.click(screen.getByRole('button', { name: /run week review/i }))

    expect(await screen.findByText(new RegExp(fixture.windowLabel))).toBeInTheDocument()
    // Not toHaveBeenCalledWith(..., expect.anything()) -- the plain GET
    // this makes has no second (init) argument at all, and
    // expect.anything() deliberately never matches undefined.
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes(`/api/runs/${sweptRunId}/findings`))).toBe(
      true,
    )
    // The mount load is allowed to hit /latest once; the sweep is not
    // allowed to hit it at all. Anything the review itself shows must
    // come from the run the sweep returned, or a second tab's Sweep-now
    // could swap /latest out between the two requests.
    expect(
      fetchMock.mock.calls.filter(([input]) => String(input).includes('/api/runs/latest/findings')).length,
    ).toBe(latestCallsBeforeSweep)
  })

  it('flags when the service ignores the window param (returns a different windowKind)', async () => {
    vi.stubGlobal('fetch', mockFetch('month'))
    const user = userEvent.setup()

    render(<ReviewReport window="week" title="Weekly review" />)
    await user.click(screen.getByRole('button', { name: /run week review/i }))

    expect(
      await screen.findByText(/may not be honoured by this service yet/i),
    ).toBeInTheDocument()
  })

  it('notes when the service response has no windowKind field at all (an older service)', async () => {
    vi.stubGlobal('fetch', mockFetch(null))
    const user = userEvent.setup()

    render(<ReviewReport window="month" title="Monthly review" />)
    await user.click(screen.getByRole('button', { name: /run month review/i }))

    expect(await screen.findByText(/no windowKind field yet/i)).toBeInTheDocument()
  })

  it('previews a brief, copies it (clipboard guarded), and dispatches it', async () => {
    vi.stubGlobal('fetch', mockFetch('week'))
    const user = userEvent.setup()
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText: vi.fn().mockResolvedValue(undefined) },
      configurable: true,
    })

    render(<ReviewReport window="week" title="Weekly review" />)
    await user.click(screen.getByRole('button', { name: /run week review/i }))
    await screen.findByText(new RegExp(fixture.windowLabel))

    await user.click(screen.getByRole('button', { name: /preview brief/i }))
    expect(await screen.findByText('Weekly brief text.')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /copy for leadership/i }))
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith('Weekly brief text.')
    expect(await screen.findByRole('button', { name: /^copied$/i })).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /dispatch/i }))
    await screen.findByText('Transport manager')
  })

  it('shows "copy not available" (without crashing) when the clipboard API is unavailable', async () => {
    vi.stubGlobal('fetch', mockFetch('week'))
    const user = userEvent.setup()
    // userEvent.setup() installs its own working clipboard stub, so
    // deleting navigator.clipboard has to happen *after* setup -- without
    // this line the guard in copyForLeadership could be deleted entirely
    // and this test would still pass against userEvent's stub, which is
    // exactly the false safety net a reviewer caught.
    Object.defineProperty(navigator, 'clipboard', { value: undefined, configurable: true })

    render(<ReviewReport window="week" title="Weekly review" />)
    await user.click(screen.getByRole('button', { name: /run week review/i }))
    await screen.findByText(new RegExp(fixture.windowLabel))
    await user.click(screen.getByRole('button', { name: /preview brief/i }))
    await screen.findByText('Weekly brief text.')

    await user.click(screen.getByRole('button', { name: /copy for leadership/i }))
    expect(await screen.findByText(/copy not available/i)).toBeInTheDocument()
  })

  it('reports on the latest run the moment it opens -- no click needed', async () => {
    vi.stubGlobal('fetch', mockFetch('week', 'present'))

    render(<ReviewReport window="week" title="Weekly review" />)

    expect(await screen.findByRole('heading', { name: /verdict mix/i })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /by metric/i })).toBeInTheDocument()
    // Said out loud, because a weekly page showing the service's latest
    // run has not swept its own window and must not imply that it has.
    expect(screen.getByText(/latest run, loaded when the page opened/i)).toBeInTheDocument()
  })

  it('counts the verdict mix straight off the payload, and omits a tier it has none of', async () => {
    vi.stubGlobal('fetch', mockFetch('week', 'present'))

    render(<ReviewReport window="week" title="Weekly review" />)
    await screen.findByRole('heading', { name: /verdict mix/i })

    // The fixture is 4 Breach, 4 Concern, 1 Watch, 1 Pass out of 10.
    expect(screen.getByText(/10 findings in this window/)).toBeInTheDocument()
    expect(screen.getByText(/8 need attention/)).toBeInTheDocument()
    const legend = screen.getByRole('img', { name: /breach/i })
    expect(legend).toHaveAccessibleName('Breach 4, Concern 4, Watch 1, Pass 1')
  })

  it('ranks the worst slices and lists the recurring findings with their action', async () => {
    vi.stubGlobal('fetch', mockFetch('week', 'present'))

    render(<ReviewReport window="week" title="Weekly review" />)
    await screen.findByRole('heading', { name: /worst slices/i })

    // The one recurring finding in the fixture (4 of the last 4 weeks) --
    // with the action string, so the report ends on what to do.
    const recurringSection = screen.getByRole('heading', { name: /recurring/i }).closest('section')
    expect(recurringSection).not.toBeNull()
    expect(within(recurringSection as HTMLElement).getByText('4 of 4')).toBeInTheDocument()
    const recurringFinding = fixture.findings.find((f) => f.recurrence?.weeks === 4)
    expect(
      within(recurringSection as HTMLElement).getByText(recurringFinding?.action ?? 'no action in fixture'),
    ).toBeInTheDocument()
  })

  it('keeps the report on screen when the sweep fails, and says the window was not re-run', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/api/runs/latest/findings')) {
        return jsonResponse({
          runId: fixture.runId,
          windowLabel: fixture.windowLabel,
          findings: fixture.findings,
          windowKind: 'week',
        })
      }
      // The live service really does 500 on POST /api/sweep?window=month
      // -- which is exactly why the whole report used to sit behind it.
      return Promise.resolve({ ok: false, status: 500, statusText: 'Internal Server Error', text: async () => '' } as Response)
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()

    render(<ReviewReport window="month" title="Monthly review" />)
    await screen.findByRole('heading', { name: /verdict mix/i })

    await user.click(screen.getByRole('button', { name: /run month review/i }))

    expect(await screen.findByText(/could not re-run the month window/i)).toBeInTheDocument()
    // Still a report, not a blank page.
    expect(screen.getByRole('heading', { name: /verdict mix/i })).toBeInTheDocument()
  })
})
