import { describe, expect, it } from 'vitest'
import { highlightedIndexes } from './highlight'

const rows = [{ nct_ids: ['NCT00000002', 'NCT00000001'] }, { nct_ids: [] }, { nct_ids: ['NCT00000003'] }]

describe('highlightedIndexes', () => {
  it('returns the rows that contain any highlighted trial', () => {
    expect(highlightedIndexes(rows, new Set(['NCT00000001']))).toEqual([0])
    expect(highlightedIndexes(rows, new Set(['NCT00000001', 'NCT00000003']))).toEqual([0, 2])
  })

  it('returns nothing when nothing is highlighted, so every row stays at full opacity', () => {
    expect(highlightedIndexes(rows, new Set())).toEqual([])
  })
})
