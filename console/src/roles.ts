import { DEFAULT_KPI_METRIC_IDS, DEFAULT_SUGGESTED_QUESTIONS } from './api/insights.ts'
import type { Audience, Finding } from './api/types.ts'
import { isAlertTier } from './api/types.ts'

// Reuses the existing Audience type (TRANSPORT_MANAGER / FACILITIES_HEAD /
// LINE_MANAGER, already used for dispatch/brief targeting) rather than a
// parallel enum -- the person viewing the console and the person a brief
// targets are the same three kinds of person.
export type Role = Audience

export interface RoleConfig {
  id: Role
  label: string
  // Sidebar paths visible for this role. A path NOT in this set still
  // renders fine if navigated to directly (deep link, back button,
  // whatever) -- there is no 403/redirect, the route table in App.tsx is
  // identical for every role. This only hides the nav *link*.
  visibleNavPaths: Set<string>
  // Overview's KPI row, by metric id -- label('metric', id) supplies the
  // title, and a metric with no `overall` finding yet (e.g.
  // cost_per_rider, not active on every deployment) just renders
  // KpiCard's existing "Not active yet" placeholder.
  kpiMetricIds: string[]
  // A short heading shown above the KPI row for this role, or null for no
  // heading (Transport manager's plain four-card row).
  kpiStripLabel: string | null
  // Overview's priority-action selection -- everyone else uses
  // isAlertTier (CONCERN or BREACH); Facilities head narrows to BREACH
  // only, since that role acts on what's serious, not everything worth
  // a Transport manager's attention.
  isPriorityFinding: (finding: Finding) => boolean
  // Applied to the whole findings array once, in App.tsx, before it
  // reaches any page -- Line manager's is the only non-trivial one.
  findingsFilter: (finding: Finding) => boolean
  // The floating assistant's suggested chips for this role.
  suggestedQuestions: string[]
}

const ALL_NAV_PATHS = new Set([
  '/',
  '/alerts',
  '/findings',
  '/employees',
  '/vendors',
  '/health',
  '/cost',
  '/reports/weekly',
  '/reports/monthly',
  '/brief',
])

// Slice labels are "<dimension> <value>" (formatSliceLabel in labels.ts
// documents the same convention) -- "shift EARLY", "shift NIGHT", etc.
function isShiftSliced(finding: Finding): boolean {
  return finding.sliceLabel.startsWith('shift ')
}

const FACILITIES_HEAD_SUGGESTED_QUESTIONS = [
  DEFAULT_SUGGESTED_QUESTIONS[0],
  'Which vendors are recurring laggards?',
  DEFAULT_SUGGESTED_QUESTIONS[2],
  DEFAULT_SUGGESTED_QUESTIONS[3],
]

export const ROLES: Record<Role, RoleConfig> = {
  // The primary role -- the complete console, unchanged from everything
  // built before Stage 7. Nothing here narrows or filters anything.
  TRANSPORT_MANAGER: {
    id: 'TRANSPORT_MANAGER',
    label: 'Transport manager',
    visibleNavPaths: ALL_NAV_PATHS,
    kpiMetricIds: DEFAULT_KPI_METRIC_IDS,
    kpiStripLabel: null,
    isPriorityFinding: (finding) => isAlertTier(finding.tier),
    findingsFilter: () => true,
    suggestedQuestions: DEFAULT_SUGGESTED_QUESTIONS,
  },

  // The second role -- genuinely different, not a re-skin: its own KPI
  // set (cost/safety/experience, not the operational four), Breach-only
  // priority actions, and a nav trimmed to what a facilities/cost-and-
  // safety reader acts on (Reports, Cost, Vendors, Alerts) rather than
  // row-by-row findings triage (no Insights table, no feed-health
  // internals -- those stay Transport manager's tools).
  FACILITIES_HEAD: {
    id: 'FACILITIES_HEAD',
    label: 'Transport & facilities head',
    // No /employees: this role acts on Breach-level cost, safety and
    // contract questions, not on which named site or shift band is hurting
    // employees this week -- the same reason it has no Insights table and
    // no feed-health internals.
    visibleNavPaths: new Set(['/', '/alerts', '/vendors', '/cost', '/reports/weekly', '/reports/monthly', '/brief']),
    kpiMetricIds: ['ota', 'cost_per_km', 'cost_per_rider', 'marshal_compliance'],
    kpiStripLabel: 'Cost · Safety · Experience',
    isPriorityFinding: (finding) => finding.tier === 'BREACH',
    findingsFilter: () => true,
    suggestedQuestions: FACILITIES_HEAD_SUGGESTED_QUESTIONS,
  },

  // Deliberately thin -- a scope cut the user asked for explicitly ("we
  // need to target only 1 role but can we accommodate 2 roles"). This is
  // a third dropdown entry, not a third built-out persona: no bespoke
  // shift board, no dedicated KPI set (reuses Transport manager's). All it
  // does is scope the same pages everyone else sees down to shift-sliced
  // findings (via `findingsFilter`, applied once in App.tsx) and trim the
  // nav to what a line-level shift supervisor plausibly needs day to day
  // (no Vendors/Cost/Data health -- those are fleet/contract-level
  // concerns, not a single shift's).
  //
  // /employees IS linked here: "which of my people were left standing, on
  // which shift band" is the most directly actionable page a line manager
  // has. It is the one page whose own breakdown is by shift band.
  LINE_MANAGER: {
    id: 'LINE_MANAGER',
    label: 'Line manager',
    visibleNavPaths: new Set(['/', '/alerts', '/findings', '/employees', '/reports/weekly', '/reports/monthly', '/brief']),
    kpiMetricIds: DEFAULT_KPI_METRIC_IDS,
    kpiStripLabel: null,
    isPriorityFinding: (finding) => isAlertTier(finding.tier),
    findingsFilter: isShiftSliced,
    suggestedQuestions: DEFAULT_SUGGESTED_QUESTIONS,
  },
}

export const ROLE_ORDER: Role[] = ['TRANSPORT_MANAGER', 'FACILITIES_HEAD', 'LINE_MANAGER']
