import { render, screen } from '@testing-library/react'
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
    vi.stubGlobal('fetch', vi.fn(() => notFound()))

    const { container } = render(<SafetyBanner runId="run-1" />)
    await new Promise((resolve) => setTimeout(resolve, 10))

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
