import type {
  AskResponse,
  Audience,
  Brief,
  Cost,
  DecomposeDimension,
  DecomposeResponse,
  DispatchAudienceResult,
  DispatchResponse,
  EmployeeImpact,
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

// A non-2xx response, carrying the status code so callers can tell the
// two cases apart that the console used to conflate: 404 means "this build
// does not serve that route", anything else (422, 500, a gateway timeout)
// means "the route exists and this particular request failed". Treating
// every non-2xx as "endpoint missing" is exactly what disabled the
// assistant against a working backend.
export class ApiError extends Error {
  readonly status: number

  constructor(status: number, statusText: string, body: string) {
    super(`${status} ${statusText}${body ? `: ${body}` : ''}`)
    this.name = 'ApiError'
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, init)
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new ApiError(res.status, res.statusText, body)
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

// Optional endpoint -- gated by the "employees" capability, not by a
// probe. Throws (ApiError) like every other real request; the Employees
// page decides what an absent endpoint looks like on screen.
export function getEmployeeImpact(runId = 'latest'): Promise<EmployeeImpact> {
  return request<EmployeeImpact>(`/api/employees/impact?runId=${encodeURIComponent(runId)}`)
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

// Throws (ApiError) rather than swallowing failures to null. Callers must
// distinguish a 404 -- this build has no /api/ask, disable the feature --
// from a 422/500/timeout, which is one question that failed and must leave
// the input enabled to retry. Availability is NOT detected by calling this;
// use getCapabilities() below.
export function ask(runId: string, question: string): Promise<AskResponse> {
  return request<AskResponse>('/api/ask', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ runId, question }),
  })
}

// Feature detection for the optional endpoints, read off GET /api/health's
// `capabilities` list -- a fixed contract with the service, whose names are
// "ask", "decompose", "safety", "employees", "cost", "dispatch-log".
//
// Returns null for "unknown": either the field is absent (an older service
// that predates it, which still serves the routes) or /api/health itself
// could not be reached. Never POST a request you know is invalid to find
// out whether a route exists -- the service rightly answers 422 and the
// answer you get back is a lie.
export async function getCapabilities(): Promise<string[] | null> {
  try {
    const health = await request<HealthStatus>('/api/health')
    return Array.isArray(health.capabilities) ? health.capabilities : null
  } catch {
    return null
  }
}

// Absence of evidence is not evidence of absence: unknown capabilities
// (null) means available. Only an explicit list that omits `name` disables
// the feature.
export function hasCapability(capabilities: string[] | null, name: string): boolean {
  return capabilities === null || capabilities.includes(name)
}
