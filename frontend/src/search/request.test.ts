import { describe, expect, it } from 'vitest'
import { EMPTY_FORM, toRequest, type SearchFormValues } from './request'

// Rules mirror SCHEMAS.md §1 / VisualizeRequest; the server stays authoritative.
function form(values: Partial<SearchFormValues>): SearchFormValues {
  return { ...EMPTY_FORM, ...values }
}

describe('toRequest', () => {
  it('trims values and omits blank optional fields', () => {
    const result = toRequest(form({ query: '  phases of melanoma trials ', drug_name: '  ', condition: ' Melanoma ' }))
    expect(result).toEqual({ ok: true, request: { query: 'phases of melanoma trials', condition: 'Melanoma' } })
  })

  it('sends the phase code and years as integers', () => {
    const result = toRequest(
      form({ query: 'trials per year', drug_name: 'pembrolizumab', trial_phase: 'PHASE3', start_year: '2015', end_year: '2020' }),
    )
    expect(result).toEqual({
      ok: true,
      request: { query: 'trials per year', drug_name: 'pembrolizumab', trial_phase: 'PHASE3', start_year: 2015, end_year: 2020 },
    })
  })

  it('rejects a blank query', () => {
    expect(toRequest(form({ query: '   ' }))).toEqual({ ok: false, errors: { query: 'Enter a question.' } })
  })

  it('rejects a query over 1000 characters after trimming', () => {
    expect(toRequest(form({ query: ` ${'q'.repeat(1000)} ` })).ok).toBe(true)
    expect(toRequest(form({ query: 'q'.repeat(1001) }))).toEqual({
      ok: false,
      errors: { query: 'Keep the question under 1,000 characters.' },
    })
  })

  it('rejects a filter over 200 characters after trimming', () => {
    expect(toRequest(form({ query: 'q', sponsor: 's'.repeat(201) }))).toEqual({
      ok: false,
      errors: { sponsor: 'Keep this under 200 characters.' },
    })
  })

  it('rejects a year that is not a whole number', () => {
    expect(toRequest(form({ query: 'q', start_year: '2015.5' }))).toEqual({
      ok: false,
      errors: { start_year: 'Enter a whole year, e.g. 2015.' },
    })
  })

  it('rejects a start year after the end year', () => {
    expect(toRequest(form({ query: 'q', start_year: '2022', end_year: '2018' }))).toEqual({
      ok: false,
      errors: { end_year: 'End year must not be before the start year.' },
    })
  })

  it('accepts equal start and end years', () => {
    expect(toRequest(form({ query: 'q', start_year: '2020', end_year: '2020' })).ok).toBe(true)
  })
})
