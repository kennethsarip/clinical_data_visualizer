import { useEffect, useMemo, useRef, useState } from 'react'
import { getTrial, type ApiResult, type StoredTrial } from '../api/client'
import { matchCitation, type Citation, type CitationMatch } from './recordMatch'
import { RecordTree } from './RecordTree'

interface Props {
  nctId: string
  title: string
  /** The citations to locate: the selected datum's for this trial, or all of the chart's. */
  citations: Citation[]
}

const STUDY_URL = 'https://clinicaltrials.gov/study/'

/** The cached record a citation was checked against (SCHEMAS.md §6), cited values highlighted. */
export function RecordViewer({ nctId, title, citations }: Props) {
  const [result, setResult] = useState<ApiResult<StoredTrial> | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    getTrial(nctId, controller.signal).then(setResult, (error: unknown) => {
      if (!(error instanceof DOMException && error.name === 'AbortError')) throw error
    })
    return () => controller.abort()
  }, [nctId])

  const link = (
    <a className="button-ghost viewer-link" href={`${STUDY_URL}${nctId}`} target="_blank" rel="noreferrer">
      Open on ClinicalTrials.gov ↗
    </a>
  )

  return (
    <article className="viewer" aria-labelledby="viewer-title">
      <header className="viewer-head">
        <span className="source-badge">ClinicalTrials.gov</span>
        <span className="viewer-id">{nctId}</span>
        <h3 id="viewer-title">{title}</h3>
        {link}
      </header>
      {result === null ? (
        <p className="viewer-note">Loading the cached record…</p>
      ) : result.kind === 'ok' ? (
        <LoadedRecord stored={result.data} citations={citations} />
      ) : (
        <p className="viewer-note">
          {result.kind === 'not_found'
            ? 'This trial is not in the cache any more, so the record behind the answer cannot be shown. ClinicalTrials.gov has the current version.'
            : `The record could not be loaded. ${'detail' in result ? result.detail : ''}`}
        </p>
      )}
    </article>
  )
}

function LoadedRecord({ stored, citations }: { stored: StoredTrial; citations: Citation[] }) {
  const container = useRef<HTMLDivElement>(null)
  const matches = useMemo(() => citations.map((c) => ({ citation: c, match: matchCitation(stored.record, c) })), [citations, stored])
  const highlights = useMemo(
    () => new Set(matches.flatMap(({ match }) => (match.status === 'found' ? match.paths : []))),
    [matches],
  )
  const changed = matches.flatMap(({ match }) => (match.status === 'changed' ? [match.message] : []))
  const section = (stored.record as { protocolSection?: Record<string, unknown> }).protocolSection ?? {}

  useEffect(() => {
    // jsdom has no scrollIntoView; browsers do.
    container.current?.querySelector('mark')?.scrollIntoView?.({ block: 'center', behavior: 'smooth' })
  }, [highlights])

  return (
    <div ref={container} className="viewer-body">
      <p className="viewer-cached">Cached {stored.fetched_at.slice(0, 10)}, the version the answer was checked against.</p>
      {changed.length > 0 && (
        <p className="viewer-warning" role="alert">
          The cached record has changed since this answer was checked. {changed.join(' ')}
        </p>
      )}
      {citations.length === 0 ? (
        <p className="viewer-note">This trial counts in this chart but is not quoted: each datum cites at most 25 trials.</p>
      ) : (
        <ul className="viewer-citations" aria-label="Citations">
          {matches.map(({ citation, match }, index) => (
            <li key={index}>{describe(citation, match)}</li>
          ))}
        </ul>
      )}
      <RecordTree section={section} highlights={highlights} />
    </div>
  )
}

function describe(citation: Citation, match: CitationMatch): string {
  switch (match.status) {
    case 'found':
      return `${citation.field} = ${citation.excerpt} · highlighted below`
    case 'absent':
      return `${citation.field} is not in this record, which is why the trial is counted`
    case 'changed':
      return `${citation.field} · changed (see above)`
  }
}
