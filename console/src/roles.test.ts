import { describe, expect, it } from 'vitest'
import { ROLES, ROLE_ORDER } from './roles.ts'
import type { Finding } from './api/types.ts'

function makeFinding(overrides: Partial<Finding>): Finding {
  return {
    id: 'f1',
    metricId: 'ota',
    metricLabel: 'On-time arrival',
    unit: '%',
    sliceLabel: 'overall',
    tier: 'BREACH',
    cause: 'BELOW_TARGET',
    observed: 59.1,
    gap: 30.9,
    confidence: 0.96,
    audiences: ['TRANSPORT_MANAGER'],
    references: [],
    evidenceSql: 'SELECT 1',
    ...overrides,
  }
}

describe('ROLES', () => {
  it('has exactly the two shipped personas, in dropdown order', () => {
    // LINE_MANAGER is deliberately absent: it is still an audience the
    // service routes briefs to, but it never got a surface of its own
    // (see roles.ts), so it is not offered as a console persona.
    expect(ROLE_ORDER).toEqual(['TRANSPORT_MANAGER', 'FACILITIES_HEAD'])
    expect(Object.keys(ROLES).sort()).toEqual(ROLE_ORDER.slice().sort())
  })

  it('Transport manager sees the complete nav and every alert-tier finding', () => {
    const role = ROLES.TRANSPORT_MANAGER
    for (const path of ['/', '/alerts', '/findings', '/vendors', '/health', '/reports/weekly', '/reports/monthly']) {
      expect(role.visibleNavPaths.has(path)).toBe(true)
    }
    expect(role.isPriorityFinding(makeFinding({ tier: 'BREACH' }))).toBe(true)
    expect(role.isPriorityFinding(makeFinding({ tier: 'CONCERN' }))).toBe(true)
    expect(role.isPriorityFinding(makeFinding({ tier: 'WATCH' }))).toBe(false)
    expect(role.findingsFilter(makeFinding({ sliceLabel: 'vendor Acme' }))).toBe(true)
    expect(role.kpiStripLabel).toBeNull()
  })

  it('Facilities head has its own KPI set, a strip label, Breach-only priority actions, and a narrower nav', () => {
    const role = ROLES.FACILITIES_HEAD
    expect(role.kpiMetricIds).toEqual(['ota', 'cost_per_km', 'cost_per_rider', 'marshal_compliance'])
    expect(role.kpiStripLabel).toBe('Cost · Safety · Experience')

    expect(role.isPriorityFinding(makeFinding({ tier: 'BREACH' }))).toBe(true)
    expect(role.isPriorityFinding(makeFinding({ tier: 'CONCERN' }))).toBe(false)

    // Genuinely different nav -- no raw Insights table, no feed-health
    // internals; Reports + Vendors + Alerts stay.
    expect(role.visibleNavPaths.has('/findings')).toBe(false)
    expect(role.visibleNavPaths.has('/health')).toBe(false)
    expect(role.visibleNavPaths.has('/vendors')).toBe(true)
    expect(role.visibleNavPaths.has('/reports/weekly')).toBe(true)

    // /cost and /brief are routed but unlinked for everyone (nav.ts), so
    // no role grants them -- the two lists cannot drift apart.
    expect(role.visibleNavPaths.has('/cost')).toBe(false)
    expect(role.visibleNavPaths.has('/brief')).toBe(false)

    expect(role.suggestedQuestions[1]).toBe('Which vendors are recurring laggards?')
  })
})
