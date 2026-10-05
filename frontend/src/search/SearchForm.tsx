import { flushSync } from 'react-dom'
import {
  useId,
  useImperativeHandle,
  useState,
  type FormEvent,
  type KeyboardEvent,
  type Ref,
} from 'react'
import type { VisualizeRequest } from '../api/client'
import { EXAMPLES } from './examples'
import { PHASE_OPTIONS } from '../vocab'
import {
  EMPTY_FORM,
  activeFilterCount,
  toRequest,
  type FormErrors,
  type SearchFormValues,
} from './request'

export interface SearchFormHandle {
  /** Open the filter row and focus one field, e.g. the anchor a clarification asked for. */
  openFilter: (field: TextField) => void
}

interface Props {
  busy: boolean
  onSubmit: (request: VisualizeRequest) => void
  ref?: Ref<SearchFormHandle>
}

export type TextField = Exclude<keyof SearchFormValues, 'query' | 'trial_phase'>

const TEXT_FIELDS: readonly { field: TextField; label: string; placeholder: string }[] = [
  { field: 'drug_name', label: 'Drug', placeholder: 'e.g. pembrolizumab' },
  { field: 'condition', label: 'Condition', placeholder: 'e.g. melanoma' },
  { field: 'sponsor', label: 'Sponsor', placeholder: 'e.g. Pfizer' },
  { field: 'country', label: 'Country', placeholder: 'e.g. Germany' },
  { field: 'start_year', label: 'Start year', placeholder: 'e.g. 2015' },
  { field: 'end_year', label: 'End year', placeholder: 'e.g. 2024' },
]

export function SearchForm({ busy, onSubmit, ref }: Props) {
  const [values, setValues] = useState<SearchFormValues>(EMPTY_FORM)
  const [errors, setErrors] = useState<FormErrors>({})
  const [filtersOpen, setFiltersOpen] = useState(false)
  const id = useId()
  const filterCount = activeFilterCount(values)

  useImperativeHandle(ref, () => ({
    openFilter(field) {
      // Render the filter row now: the input does not exist while it is collapsed.
      flushSync(() => setFiltersOpen(true))
      document.getElementById(`${id}-${field}`)?.focus()
    },
  }))

  function set<K extends keyof SearchFormValues>(field: K, value: SearchFormValues[K]) {
    setValues((current) => ({ ...current, [field]: value }))
    setErrors((current) => ({ ...current, [field]: undefined }))
  }

  function submit(next: SearchFormValues) {
    const result = toRequest(next)
    if (!result.ok) {
      setErrors(result.errors)
      return
    }
    setErrors({})
    onSubmit(result.request)
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (!busy) submit(values)
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault()
      if (!busy) submit(values)
    }
  }

  function runExample(query: string) {
    // Run the example exactly as it was verified: stale filters would change its answer.
    const next = { ...EMPTY_FORM, query }
    setValues(next)
    if (!busy) submit(next)
  }

  const errorId = (field: keyof SearchFormValues) => `${id}-${field}-error`
  const describedBy = (field: keyof SearchFormValues) => (errors[field] ? errorId(field) : undefined)

  return (
    <div className="search">
      <form className="card search-card" onSubmit={handleSubmit} noValidate>
        <div className="card-header">Ask about clinical trials</div>
        <div className="card-body">
          <textarea
            className="query-box"
            aria-label="Ask about clinical trials"
            aria-invalid={Boolean(errors.query)}
            aria-describedby={describedBy('query')}
            placeholder="e.g. How has the number of pembrolizumab trials changed since 2015?"
            value={values.query}
            onChange={(event) => set('query', event.target.value)}
            onKeyDown={handleKeyDown}
          />
          {errors.query && (
            <p className="field-error" id={errorId('query')}>
              {errors.query}
            </p>
          )}

          {filtersOpen && (
            <div className="filters" id={`${id}-filters`}>
              {TEXT_FIELDS.map(({ field, label, placeholder }) => (
                <div className="field" key={field}>
                  <label className="field-label" htmlFor={`${id}-${field}`}>
                    {label}
                  </label>
                  <input
                    id={`${id}-${field}`}
                    className="input"
                    inputMode={field.endsWith('_year') ? 'numeric' : undefined}
                    placeholder={placeholder}
                    value={values[field]}
                    aria-invalid={Boolean(errors[field])}
                    aria-describedby={describedBy(field)}
                    onChange={(event) => set(field, event.target.value)}
                  />
                  {errors[field] && (
                    <span className="field-error" id={errorId(field)}>
                      {errors[field]}
                    </span>
                  )}
                </div>
              ))}
              <div className="field">
                <label className="field-label" htmlFor={`${id}-trial_phase`}>
                  Phase
                </label>
                <select
                  id={`${id}-trial_phase`}
                  className="input"
                  value={values.trial_phase}
                  onChange={(event) => set('trial_phase', event.target.value as SearchFormValues['trial_phase'])}
                >
                  <option value="">Any phase</option>
                  {PHASE_OPTIONS.map(({ value, label }) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          )}

          <div className="search-actions">
            <button
              type="button"
              className="button-ghost"
              aria-expanded={filtersOpen}
              aria-controls={`${id}-filters`}
              onClick={() => setFiltersOpen((open) => !open)}
            >
              Filters
              {filterCount > 0 && <span className="count-badge">{filterCount}</span>}
            </button>
            <button type="submit" className="button-primary" disabled={busy}>
              Visualize
            </button>
          </div>
        </div>
      </form>

      <div className="examples" role="group" aria-label="Example questions">
        {EXAMPLES.map((example) => (
          <button
            key={example.evalId}
            type="button"
            className="example-chip"
            disabled={busy}
            onClick={() => runExample(example.query)}
          >
            <span className="chip-tag">{example.label}</span>
            {example.query}
          </button>
        ))}
      </div>
    </div>
  )
}
