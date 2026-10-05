import { describe, expect, it } from 'vitest'
import { cappedNotice } from './sample'

const entry = (cohort: string | null, fetched: number, total: number) => ({ cohort, fetched, total, capped: fetched < total })

describe('cappedNotice (meta.sample, SCHEMAS.md §4)', () => {
  it('says nothing when every trial was fetched', () => {
    expect(cappedNotice([entry(null, 703, 703)])).toBeNull()
  })

  it('names the sample size and the total for one sample', () => {
    expect(cappedNotice([entry(null, 10000, 123756)])).toBe(
      'Counts come from 10,000 of 123,756 matching trials (the fetch cap), so they are lower than the registry totals.',
    )
  })

  it('names each capped cohort and leaves out the complete ones', () => {
    expect(cappedNotice([entry('Lung cancer', 10000, 14800), entry('Colorectal cancer', 9200, 9200), entry('Breast cancer', 10000, 30111)])).toBe(
      'Counts come from capped samples (the fetch cap), so they are lower than the registry totals: Lung cancer 10,000 of 14,800; Breast cancer 10,000 of 30,111.',
    )
  })
})
