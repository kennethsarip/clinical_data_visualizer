import type { ReactNode } from 'react'
import type { ApiResult, FieldError, VisualizeResponse } from '../api/client'
import type { components } from '../api/types'
import { FilterChips } from '../answer/FilterChips'
import { filterLabel } from '../vocab'

type Schemas = components['schemas']
interface Props {
  result: ApiResult<VisualizeResponse>
  onRetry: () => void
  onEditQuestion: () => void
  onAsk: (query: string) => void
}

/** Every outcome except a chart: non-`ok` statuses (SCHEMAS.md §5) and HTTP errors. */
export function StatusView({ result, onRetry, onEditQuestion, onAsk }: Props) {
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
      return <Clarification meta={response.meta} onEditQuestion={onEditQuestion} onAsk={onAsk} />
    case 'no_results':
      return <NoResults meta={response.meta} />
    case 'degraded':
      return <Degraded meta={response.meta} />
    case 'ok':
      return null
  }
}

function Clarification({
  meta,
  onEditQuestion,
  onAsk,
}: {
  meta: Schemas['ClarificationMeta']
  onEditQuestion: () => void
  onAsk: (query: string) => void
}) {
  // The question box is the only input, so the answer to a clarification is a rephrased question:
  // the planner's suggestion in one click (SCHEMAS.md §5), or the user's own edit.
  const suggestion = meta.suggested_query
  return (
    <Panel title="More detail needed">
      <Notes notes={meta.notes} />
      {meta.unapplied.length > 0 && (
        <ul className="pill-list" aria-label="Not applied">
          {meta.unapplied.map(({ quote }) => (
            <li key={quote}>{quote}</li>
          ))}
        </ul>
      )}
      <div className="clarify-actions">
        {suggestion && (
          <button type="button" className="button-primary" onClick={() => onAsk(suggestion)}>
            Ask: {suggestion}
          </button>
        )}
        <button type="button" className="example-chip" onClick={onEditQuestion}>
          Edit the question
        </button>
      </div>
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
      <FilterChips filters={meta.filters} label="Filters applied" />
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

function Notes({ notes }: { notes: string[] }) {
  return notes.map((note) => (
    <p key={note} className="note">
      {note}
    </p>
  ))
}

function Panel({ title, tone, onRetry, children }: { title: string; tone?: 'error'; onRetry?: () => void; children: ReactNode }) {
  return (
    <section className={`status${tone ? ` status-${tone}` : ''}`} aria-labelledby="status-title">
      <h2 id="status-title">{title}</h2>
      <div className="status-body">
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
