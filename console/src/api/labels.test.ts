import { describe, expect, it } from 'vitest'
import { causePhrase, formatSliceLabel, label } from './labels.ts'

describe('label', () => {
  it('renders tiers in Title Case', () => {
    expect(label('tier', 'BREACH')).toBe('Breach')
    expect(label('tier', 'PASS')).toBe('Pass')
  })

  it('renders audiences as sentence case', () => {
    expect(label('audience', 'TRANSPORT_MANAGER')).toBe('Transport manager')
    expect(label('audience', 'FACILITIES_HEAD')).toBe('Facilities head')
  })

  it('falls back to a humanised form for an unrecognised value', () => {
    expect(label('audience', 'REGIONAL_LEAD')).toBe('Regional lead')
    expect(label('channel', 'whatsapp')).toBe('Whatsapp')
  })
})

describe('causePhrase', () => {
  it('maps a known cause to its plain-English phrase', () => {
    expect(causePhrase('BELOW_TARGET')).toBe('below its SLA target')
  })

  it('humanises an unrecognised cause rather than rendering it raw', () => {
    expect(causePhrase('NEW_UNSEEN_CAUSE')).toBe('New unseen cause')
  })
})

describe('formatSliceLabel', () => {
  it('leaves a proper-noun dimension value exactly as sent', () => {
    expect(formatSliceLabel('vendor Vikram Mikhailov Travel')).toBe('Vendor: Vikram Mikhailov Travel')
    expect(formatSliceLabel('site Clearwater Campus')).toBe('Site: Clearwater Campus')
    expect(formatSliceLabel('tenant vanta-Aus')).toBe('Business unit: vanta-Aus')
  })

  it('renders "overall" as-is', () => {
    expect(formatSliceLabel('overall')).toBe('Overall')
  })

  it('humanises an enum-like dimension value (mode)', () => {
    expect(formatSliceLabel('mode BUS')).toBe('Mode: Bus')
    expect(formatSliceLabel('mode CAB')).toBe('Mode: Cab')
    expect(formatSliceLabel('mode SPOT_2.0')).toBe('Mode: Spot 2.0')
  })

  it('humanises an enum-like dimension value (direction)', () => {
    expect(formatSliceLabel('direction LOGIN')).toBe('Direction: Login')
    expect(formatSliceLabel('direction LOGOUT')).toBe('Direction: Logout')
  })

  it('humanises an enum-like dimension value (shift)', () => {
    expect(formatSliceLabel('shift EARLY')).toBe('Shift: Early')
    expect(formatSliceLabel('shift DAY')).toBe('Shift: Day')
    expect(formatSliceLabel('shift EVENING')).toBe('Shift: Evening')
    expect(formatSliceLabel('shift NIGHT')).toBe('Shift: Night')
  })

  it('falls back to humanise() for an enum-like value not yet in the map', () => {
    expect(formatSliceLabel('mode FERRY')).toBe('Mode: Ferry')
  })

  it('passes an unrecognised dimension through unchanged', () => {
    expect(formatSliceLabel('region APAC')).toBe('region APAC')
  })
})
