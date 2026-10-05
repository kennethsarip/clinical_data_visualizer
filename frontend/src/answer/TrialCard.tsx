import type { Citation, TrialSummary } from './SourcesPanel'

interface Props {
  nctId: string
  number: number
  trial: TrialSummary
  /** Set while a datum is selected: this trial's citations in that datum ([] if capped out). */
  citations: Citation[] | null
  onHover: (nctId: string | null) => void
  onOpen: (nctId: string) => void
}

const STUDY_URL = 'https://clinicaltrials.gov/study/'
const MAX_CONDITIONS = 3

export function TrialCard({ nctId, number, trial, citations, onHover, onOpen }: Props) {
  const extra = trial.conditions.length - MAX_CONDITIONS
  return (
    <li
      id={`source-${nctId}`}
      className="source-card"
      tabIndex={0}
      onMouseEnter={() => onHover(nctId)}
      onMouseLeave={() => onHover(null)}
      onFocus={() => onHover(nctId)}
      onBlur={() => onHover(null)}
      // The NCT ID link opens ClinicalTrials.gov itself; anywhere else opens the cached record.
      onClick={(event) => {
        if (!(event.target as HTMLElement).closest('a')) onOpen(nctId)
      }}
      onKeyDown={(event) => {
        if (event.key === 'Enter' && event.target === event.currentTarget) onOpen(nctId)
      }}
      aria-label={`Source ${number}: ${trial.brief_title}. Press Enter to view the record.`}
    >
      <div className="source-head">
        <span className="source-number" data-testid="source-number">
          {number}
        </span>
        <span className="source-badge">ClinicalTrials.gov</span>
        <a className="source-id" href={`${STUDY_URL}${nctId}`} target="_blank" rel="noreferrer">
          {nctId}
        </a>
      </div>
      <p className="source-title">{trial.brief_title}</p>
      {trial.official_title && (
        <p className="source-description" data-testid="description">
          {trial.official_title}
        </p>
      )}
      <p className="source-meta">
        <span>{trial.start_date ?? 'Start date not registered'}</span>
        <span aria-hidden="true"> · </span>
        <span>{trial.sponsor_name}</span>
      </p>
      <ul className="source-chips" aria-label="Trial details">
        <li>{trial.overall_status}</li>
        <li>{trial.phase}</li>
        {trial.conditions.slice(0, MAX_CONDITIONS).map((condition) => (
          <li key={condition} className="chip-condition">
            {condition}
          </li>
        ))}
        {extra > 0 && <li className="chip-condition">+{extra} more</li>}
      </ul>
      {citations && <Excerpts citations={citations} />}
    </li>
  )
}

function Excerpts({ citations }: { citations: Citation[] }) {
  if (citations.length === 0) {
    return (
      <p className="source-excerpt muted" data-testid="excerpt">
        Not cited: each datum cites at most 25 trials, and this one counts without a quoted excerpt.
      </p>
    )
  }
  return (
    <div className="source-excerpt" data-testid="excerpt">
      {citations.map((citation, index) => (
        <p key={index}>
          {citation.excerpt === null ? (
            <span className="excerpt-absent">
              <code>{citation.field}</code> is not in this record, which is why the trial is counted here.
            </span>
          ) : (
            <>
              <code>{citation.field}</code> <mark>{citation.excerpt}</mark>
            </>
          )}
        </p>
      ))}
    </div>
  )
}
