import type { ReactNode } from 'react'
import type { ApiResult, FieldError, VisualizeResponse } from '../api/client'
import type { components } from '../api/types'
import { filterLabel, formatFilterValue } from '../vocab'

type Schemas = components['schemas']
export type Anchor = Schemas['ClarificationMeta']['missing'][number]

interface Props {
  result: ApiResult<VisualizeResponse>
  onRetry: () => void
  onAddAnchor: (anchor: Anchor) => void
}

const ANCHOR_TEXT: Record<Anchor, string> = {
  drug_name: 'Add a drug',
  condition: 'Add a condition',
  sponsor: 'Add a sponsor',
}

/** Every outcome except a chart: non-`ok` statuses (SCHEMAS.md §5) and HTTP errors. */
export function StatusView({ result, onRetry, onAddAnchor }: Props) {
  if (result.kind === 'invalid') return <Invalid errors={result.errors} />
  if (result.kind === 'unavailable') {
    return (
      <Panel title="A data service is unavailable" tone="error" onRetry={onRetry}>
        <p>ClinicalTrials.gov or the language model did not respond. Trying again may work.</p>
        <p className="detail">{result.detail}</p>
      </Panel>
    )
  }
  if (result.kind !== 'ok') {
    return (
      <Panel title="Something went wrong" tone="error" onRetry={onRetry}>
        <p className="detail">{result.detail}</p>
      </Panel>
    )
  }
  const response = result.data
  switch (response.status) {
    case 'clarification_needed':
      return <Clarification meta={response.meta} onAddAnchor={onAddAnchor} />
    case 'no_results':
      return <NoResults meta={response.meta} />
    case 'degraded':
      return <Degraded meta={response.meta} />
    case 'ok':
      return null
  }
}

function Clarification({ meta, onAddAnchor }: { meta: Schemas['ClarificationMeta']; onAddAnchor: Props['onAddAnchor'] }) {
  return (
    <Panel title="More detail needed">
      <Notes notes={meta.notes} />
      {meta.missing.length > 0 && (
        <div className="suggestions" role="group" aria-label="Add what the question is about">
          {meta.missing.map((anchor) => (
            <button key={anchor} type="button" className="example-chip" onClick={() => onAddAnchor(anchor)}>
              {ANCHOR_TEXT[anchor]}
            </button>
          ))}
        </div>
      )}
    </Panel>
  )
}

function NoResults({ meta }: { meta: Schemas['NoResultsMeta'] }) {
  if (meta.not_found.length > 0) {
    return (
      <Panel title="Not found on ClinicalTrials.gov">
        <ul className="pill-list" aria-label="Not found">
          {meta.not_found.map((name) => (
            <li key={name}>{name}</li>
          ))}
        </ul>
        <Notes notes={meta.notes} />
      </Panel>
    )
  }
  return (
    <Panel title="No matching trials">
      <AppliedFilters filters={meta.filters} />
      <Notes notes={meta.notes} />
    </Panel>
  )
}

function Degraded({ meta }: { meta: Schemas['DegradedMeta'] }) {
  return (
    <Panel title="No verified chart" tone="error">
      <p>The answer failed a verification check, so it is not shown. Rephrasing the question may help.</p>
      <ul className="check-list" aria-label="Failed checks">
        {meta.errors.map((error, index) => (
          <li key={index}>
            <code>{error.check}</code>: {error.message}
          </li>
        ))}
      </ul>
      <Notes notes={meta.notes} />
    </Panel>
  )
}

function Invalid({ errors }: { errors: FieldError[] }) {
  return (
    <Panel title="The request was rejected" tone="error">
      <ul className="check-list">
        {errors.map((error, index) => {
          const field = error.loc.length > 1 ? String(error.loc[error.loc.length - 1]) : null
          return <li key={index}>{field ? `${filterLabel(field)}: ${error.msg}` : error.msg}</li>
        })}
      </ul>
    </Panel>
  )
}

function AppliedFilters({ filters }: { filters: Schemas['Filters'] }) {
  const entries = [...Object.entries(filters.stated), ...Object.entries(filters.inferred)] as [string, string | number][]
  if (entries.length === 0) return null
  return (
    <ul className="pill-list" aria-label="Filters applied">
      {entries.map(([key, value]) => (
        <li key={key}>
          {filterLabel(key)}: {formatFilterValue(key, value)}
        </li>
      ))}
    </ul>
  )
}

function Notes({ notes }: { notes: string[] }) {
  return notes.map((note) => (
    <p key={note} className="note">
      {note}
    </p>
  ))
}

function Panel({ title, tone, onRetry, children }: { title: string; tone?: 'error'; onRetry?: () => void; children: ReactNode }) {
  return (
    <section className={`card status-card${tone ? ` status-${tone}` : ''}`} aria-labelledby="status-title">
      <div className="card-header">
        <h2 id="status-title">{title}</h2>
      </div>
      <div className="card-body">
        {children}
        {onRetry && (
          <button type="button" className="button-primary retry" onClick={onRetry}>
            Try again
          </button>
        )}
      </div>
    </section>
  )
}
