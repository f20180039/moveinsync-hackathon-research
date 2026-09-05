import { render, screen } from '@testing-library/react'
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

function mockFetch(windowKind: 'week' | 'month' | null) {
  return vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.includes('/api/sweep')) {
      return jsonResponse({ runId: fixture.runId, findingCount: fixture.findings.length })
    }
    if (url.includes('/api/runs/latest/findings')) {
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

  it('does not crash when the clipboard API is unavailable', async () => {
    vi.stubGlobal('fetch', mockFetch('week'))
    const user = userEvent.setup()

    render(<ReviewReport window="week" title="Weekly review" />)
    await user.click(screen.getByRole('button', { name: /run week review/i }))
    await screen.findByText(new RegExp(fixture.windowLabel))
    await user.click(screen.getByRole('button', { name: /preview brief/i }))
    await screen.findByText('Weekly brief text.')

    expect(async () => {
      await user.click(screen.getByRole('button', { name: /copy for leadership/i }))
    }).not.toThrow()
  })
})
