import type {
  Audience,
  Brief,
  Cost,
  DispatchAudienceResult,
  DispatchResponse,
  FeedHealth,
  FindingsResponse,
  HealthStatus,
  SweepResult,
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

export function getLatestFindings(): Promise<FindingsResponse> {
  return request<FindingsResponse>('/api/runs/latest/findings')
}

export function getFeedHealth(): Promise<FeedHealth[]> {
  return request<FeedHealth[]>('/api/health/feeds')
}

export function getBrief(runId: string, audience: Audience): Promise<Brief> {
  return request<Brief>(`/api/runs/${runId}/brief?audience=${audience}`)
}

export function dispatch(runId: string): Promise<DispatchResponse> {
  return request<DispatchResponse>(`/api/dispatch/${runId}`, { method: 'POST' })
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

export function sweepNow(): Promise<SweepResult> {
  return request<SweepResult>('/api/sweep', { method: 'POST' })
}

export function getHealth(): Promise<HealthStatus> {
  return request<HealthStatus>('/api/health')
}
