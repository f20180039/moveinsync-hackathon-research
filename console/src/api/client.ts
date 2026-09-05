import type {
  AskResponse,
  Audience,
  Brief,
  Cost,
  DecomposeDimension,
  DecomposeResponse,
  DispatchAudienceResult,
  DispatchResponse,
  FeedHealth,
  Finding,
  FindingsResponse,
  HealthStatus,
  SafetySummary,
  SweepResult,
  SweepWindow,
} from './types.ts'

// Trim a trailing slash so a pasted base URL with a stray "/" doesn't turn
// into a doubled slash that 404s and looks like a routing bug. In dev, an
// empty base lets the Vite proxy handle `/api`; in production this must be
// the deployed API's origin.
const API_BASE = (import.meta.env.VITE_API_BASE ?? '').replace(/\/+$/, '')

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, init)
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(`${res.status} ${res.statusText}${body ? `: ${body}` : ''}`)
  }
  return (await res.json()) as T
}

// For an endpoint that's still landing on the service, or is explicitly
// optional (the dispatch log, /ask, /decompose on an older service): a 404
// or any other failure means "not available here", not a page error. Every
// caller feature-detects by getting `null` back rather than a thrown error.
async function tryRequest<T>(path: string, init?: RequestInit): Promise<T | null> {
  try {
    return await request<T>(path, init)
  } catch {
    return null
  }
}

export function getLatestFindings(): Promise<FindingsResponse> {
  return request<FindingsResponse>('/api/runs/latest/findings')
}

// Fetches the findings for a *specific* run rather than whatever happens
// to be latest right now -- a caller that just triggered a sweep (Review
// reports) must use this with the runId the sweep itself returned, or a
// second tab's Sweep-now (or the TopBar's) can swap /latest out from
// under it between the sweep call and the findings call.
export function getRunFindings(runId: string): Promise<FindingsResponse> {
  return request<FindingsResponse>(`/api/runs/${runId}/findings`)
}

export function getFinding(id: string): Promise<Finding> {
  return request<Finding>(`/api/findings/${id}`)
}

// Landing on the service partition -- dim is required by the (future)
// contract; feature-detect with `decomposeFinding(...).then(...) : null`.
export function decomposeFinding(findingId: string, dim: DecomposeDimension): Promise<DecomposeResponse | null> {
  return tryRequest<DecomposeResponse>(`/api/findings/${findingId}/decompose?dim=${dim}`)
}

export function getFeedHealth(): Promise<FeedHealth[]> {
  return request<FeedHealth[]>('/api/health/feeds')
}

export function getBrief(runId: string, audience: Audience): Promise<Brief> {
  return request<Brief>(`/api/runs/${runId}/brief?audience=${audience}`)
}

// `audiences` lets a caller (e.g. "Escalate") target a specific audience
// rather than whatever the service dispatches by default.
export function dispatch(runId: string, audiences?: Audience[]): Promise<DispatchResponse> {
  return request<DispatchResponse>(`/api/dispatch/${runId}`, {
    method: 'POST',
    ...(audiences && {
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ audiences }),
    }),
  })
}

// Optional endpoint -- not part of the frozen contract. Callers should
// treat a rejection (404, or any other failure) as "no log available" and
// hide the section, not as a page-level error.
export function getDispatchLog(): Promise<DispatchAudienceResult[]> {
  return request<DispatchAudienceResult[]>('/api/dispatch/log')
}

export function getCost(): Promise<Cost> {
  return request<Cost>('/api/cost')
}

// `window` is landing on the service partition -- omit it for the existing
// behaviour; an older service that ignores the query param still gets a
// valid POST /api/sweep.
export function sweepNow(window?: SweepWindow): Promise<SweepResult> {
  const query = window ? `?window=${window}` : ''
  return request<SweepResult>(`/api/sweep${query}`, { method: 'POST' })
}

export function getHealth(): Promise<HealthStatus> {
  return request<HealthStatus>('/api/health')
}

// Landing on the service partition, shape not yet confirmed -- tries the
// per-run endpoint first (per-run data is more specific than a global
// health line); feature-detects to null on any failure so the safety
// banner simply doesn't render rather than erroring the page.
export function getSafety(runId: string): Promise<SafetySummary | null> {
  return tryRequest<SafetySummary>(`/api/runs/${runId}/safety`)
}

// Not live yet -- every caller must feature-detect (null -> hide/disable
// the ask bar's send path) rather than assume this exists.
export function ask(runId: string, question: string): Promise<AskResponse | null> {
  return tryRequest<AskResponse>('/api/ask', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ runId, question }),
  })
}
