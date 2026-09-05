import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { SafetyBanner } from './SafetyBanner.tsx'

function notFound() {
  return Promise.resolve({ ok: false, status: 404, statusText: 'Not Found', text: async () => '' } as Response)
}

function jsonResponse(body: unknown) {
  return Promise.resolve({ ok: true, json: async () => body } as Response)
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('SafetyBanner', () => {
  it('renders nothing when the endpoint 404s (not landed yet)', async () => {
    const fetchMock = vi.fn((_input: RequestInfo | URL) => notFound())
    vi.stubGlobal('fetch', fetchMock)

    const { container } = render(<SafetyBanner runId="run-1" />)
    // Not a bare setTimeout -- wait for the actual thing that has to
    // happen (the mount-effect's fetch firing and its .then() settling)
    // rather than an arbitrary delay guessed to be long enough.
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([url]) => String(url).includes('/safety'))).toBe(true),
    )

    expect(container.querySelector('.safety-banner')).not.toBeInTheDocument()
  })

  it('renders the sentence, humanising the metric, when present', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        jsonResponse({ metric: 'WOMAN_TRAVELLING_ALONE', trips: 412, escortPresentPct: 6 }),
      ),
    )

    render(<SafetyBanner runId="run-1" />)

    expect(
      await screen.findByText(
        'Safety: MoveInSync raised Woman travelling alone on 412 trips this week; an escort was present on 6%.',
      ),
    ).toBeInTheDocument()
  })
})
