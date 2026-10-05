// Display labels for API codes and filter keys. Codes and labels come from the drift-checked
// OpenAPI schema, where the backend publishes vocab.py's labels as `x-labels`, so there is no
// second copy of the vocabulary to keep in sync.
import openapi from '../openapi.json'
import type { components } from './api/types'

type Phase = components['schemas']['Phase']
type Status = components['schemas']['Status']

interface LabelledEnum<T extends string> {
  enum: T[]
  'x-labels': Record<T, string>
}

const PHASE = openapi.components.schemas.Phase as LabelledEnum<Phase>
const STATUS = openapi.components.schemas.Status as LabelledEnum<Status>

// Every key `meta.filters` can carry (FilterKey in app/schemas.py).
const FILTER_LABELS: Record<string, string> = {
  drug_name: 'Drug',
  condition: 'Condition',
  sponsor: 'Sponsor',
  country: 'Country',
  trial_phase: 'Phase',
  overall_status: 'Status',
  start_year: 'Start year',
  end_year: 'End year',
}

export function filterLabel(key: string): string {
  return FILTER_LABELS[key] ?? key
}

export function formatFilterValue(key: string, value: string | number): string {
  const labels: Record<string, string> =
    key === 'trial_phase' ? PHASE['x-labels'] : key === 'overall_status' ? STATUS['x-labels'] : {}
  return labels[String(value)] ?? String(value)
}

/** The checks every `ok` response passed (app/checks.py CHECK_RULES, published as `x-checks`). */
export const CHECKS: readonly { name: string; rule: string }[] = (openapi as unknown as { 'x-checks': { name: string; rule: string }[] })['x-checks']
