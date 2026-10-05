// Form values -> request body. The checks mirror VisualizeRequest (SCHEMAS.md §1) so a user sees
// a mistake before a round trip; the server re-validates and stays authoritative.
import type { VisualizeRequest } from '../api/client'
import type { components } from '../api/types'

type Phase = components['schemas']['Phase']

// Mirrors QUERY_MAX_LENGTH and FILTER_TEXT_MAX_LENGTH in app/schemas.py.
const QUERY_MAX_LENGTH = 1000
const FILTER_TEXT_MAX_LENGTH = 200

const TEXT_FILTERS = ['drug_name', 'condition', 'sponsor', 'country'] as const

export interface SearchFormValues {
  query: string
  drug_name: string
  condition: string
  sponsor: string
  country: string
  trial_phase: Phase | ''
  start_year: string
  end_year: string
}

export const EMPTY_FORM: SearchFormValues = {
  query: '',
  drug_name: '',
  condition: '',
  sponsor: '',
  country: '',
  trial_phase: '',
  start_year: '',
  end_year: '',
}

export type FormErrors = Partial<Record<keyof SearchFormValues, string>>

export type BuildResult =
  | { ok: true; request: VisualizeRequest }
  | { ok: false; errors: FormErrors }

export function toRequest(values: SearchFormValues): BuildResult {
  const errors: FormErrors = {}
  const query = values.query.trim()
  if (!query) errors.query = 'Enter a question.'
  else if (query.length > QUERY_MAX_LENGTH) errors.query = 'Keep the question under 1,000 characters.'

  const request: VisualizeRequest = { query }
  for (const field of TEXT_FILTERS) {
    const value = values[field].trim()
    if (!value) continue // a client omits a filter it doesn't use; blank is not "no filter"
    if (value.length > FILTER_TEXT_MAX_LENGTH) errors[field] = 'Keep this under 200 characters.'
    else request[field] = value
  }
  if (values.trial_phase) request.trial_phase = values.trial_phase

  const start = parseYear(values.start_year)
  const end = parseYear(values.end_year)
  if (start === 'invalid') errors.start_year = 'Enter a whole year, e.g. 2015.'
  else if (start !== null) request.start_year = start
  if (end === 'invalid') errors.end_year = 'Enter a whole year, e.g. 2015.'
  else if (end !== null) request.end_year = end
  if (typeof start === 'number' && typeof end === 'number' && start > end) {
    errors.end_year = 'End year must not be before the start year.'
  }

  return Object.keys(errors).length ? { ok: false, errors } : { ok: true, request }
}

/** Number of optional filters with a value, for the collapsed filter toggle. */
export function activeFilterCount(values: SearchFormValues): number {
  const { query: _query, ...filters } = values
  return Object.values(filters).filter((value) => value.trim() !== '').length
}

function parseYear(raw: string): number | null | 'invalid' {
  const value = raw.trim()
  if (!value) return null
  return /^-?\d+$/.test(value) ? Number(value) : 'invalid'
}
