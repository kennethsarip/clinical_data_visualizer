import { describe, expect, it } from 'vitest'
import { PHASE_OPTIONS } from './phases'

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
