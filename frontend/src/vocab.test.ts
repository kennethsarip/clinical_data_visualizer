import { describe, expect, it } from 'vitest'
import { PHASE_OPTIONS, filterLabel, formatFilterValue } from './vocab'

describe('phase options', () => {
  it('lists every phase code with its vocab label, in enum order', () => {
    expect(PHASE_OPTIONS).toEqual([
      { value: 'NA', label: 'Not Applicable' },
      { value: 'EARLY_PHASE1', label: 'Early Phase 1' },
      { value: 'PHASE1', label: 'Phase 1' },
      { value: 'PHASE2', label: 'Phase 2' },
      { value: 'PHASE3', label: 'Phase 3' },
      { value: 'PHASE4', label: 'Phase 4' },
    ])
  })
})

describe('filter display', () => {
  it('names every filter key a response can carry (SCHEMAS.md §4)', () => {
    expect(filterLabel('drug_name')).toBe('Drug')
    expect(filterLabel('condition')).toBe('Condition')
    expect(filterLabel('sponsor')).toBe('Sponsor')
    expect(filterLabel('country')).toBe('Country')
    expect(filterLabel('trial_phase')).toBe('Phase')
    expect(filterLabel('overall_status')).toBe('Status')
    expect(filterLabel('start_year')).toBe('Start year')
    expect(filterLabel('end_year')).toBe('End year')
  })

  it('shows codes as their vocab labels and other values as given', () => {
    expect(formatFilterValue('trial_phase', 'PHASE3')).toBe('Phase 3')
    expect(formatFilterValue('overall_status', 'RECRUITING')).toBe('Recruiting')
    expect(formatFilterValue('start_year', 2015)).toBe('2015')
    expect(formatFilterValue('condition', 'Melanoma')).toBe('Melanoma')
  })

  it('shows an unknown code as-is rather than hiding it', () => {
    expect(formatFilterValue('trial_phase', 'PHASE9')).toBe('PHASE9')
  })
})
