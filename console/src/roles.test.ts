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
  it('has exactly the three roles, in dropdown order', () => {
    expect(ROLE_ORDER).toEqual(['TRANSPORT_MANAGER', 'FACILITIES_HEAD', 'LINE_MANAGER'])
    expect(Object.keys(ROLES).sort()).toEqual(ROLE_ORDER.slice().sort())
  })

  it('Transport manager sees the complete nav and every alert-tier finding', () => {
    const role = ROLES.TRANSPORT_MANAGER
    for (const path of ['/', '/alerts', '/findings', '/vendors', '/health', '/cost', '/reports/weekly', '/reports/monthly', '/brief']) {
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
    // internals; Reports + Cost + Vendors + Alerts stay.
    expect(role.visibleNavPaths.has('/findings')).toBe(false)
    expect(role.visibleNavPaths.has('/health')).toBe(false)
    expect(role.visibleNavPaths.has('/cost')).toBe(true)
    expect(role.visibleNavPaths.has('/reports/weekly')).toBe(true)
    expect(role.visibleNavPaths.has('/brief')).toBe(true)

    expect(role.suggestedQuestions[1]).toBe('Which vendors are recurring laggards?')
  })

  it('Line manager is thin: Transport manager\'s KPI set and priority rule, only findings/nav scoped to shift-sliced items', () => {
    const role = ROLES.LINE_MANAGER
    expect(role.kpiMetricIds).toEqual(ROLES.TRANSPORT_MANAGER.kpiMetricIds)
    expect(role.kpiStripLabel).toBeNull()
    expect(role.suggestedQuestions).toEqual(ROLES.TRANSPORT_MANAGER.suggestedQuestions)

    expect(role.findingsFilter(makeFinding({ sliceLabel: 'shift NIGHT' }))).toBe(true)
    expect(role.findingsFilter(makeFinding({ sliceLabel: 'shift EARLY' }))).toBe(true)
    expect(role.findingsFilter(makeFinding({ sliceLabel: 'vendor Acme' }))).toBe(false)
    expect(role.findingsFilter(makeFinding({ sliceLabel: 'overall' }))).toBe(false)

    // Nav is trimmed too (fleet/contract-level pages hidden), but no
    // bespoke page is added -- every visible path is one of the existing
    // routes.
    expect(role.visibleNavPaths.has('/vendors')).toBe(false)
    expect(role.visibleNavPaths.has('/cost')).toBe(false)
    for (const path of role.visibleNavPaths) {
      expect(ROLES.TRANSPORT_MANAGER.visibleNavPaths.has(path)).toBe(true)
    }
  })
})
