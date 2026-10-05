import { useState } from 'react'
import type { components } from '../api/types'
import { RecordViewer } from '../viewer/RecordViewer'
import type { SelectedRow } from './selection'
import { trialNumbers } from './selection'
import { TrialCard } from './TrialCard'

export type TrialSummary = components['schemas']['TrialSummary']
export type Citation = components['schemas']['Citation']

export type PanelTab = 'sources' | 'viewer'

interface Props {
  trials: Record<string, TrialSummary>
  selection: SelectedRow | null
  tab: PanelTab
  /** The trial open in the Viewer tab, if any. */
  viewing: string | null
  citationsFor: (nctId: string) => Citation[]
  onTab: (tab: PanelTab) => void
  onOpen: (nctId: string) => void
  onClearSelection: () => void
  onHover: (nctId: string | null) => void
}

const PAGE = 25

/** The trials behind the chart (SCHEMAS.md §2 `trials`), filtered to a clicked datum. */
export function SourcesPanel(props: Props) {
  const { trials, tab, viewing, onTab } = props
  return (
    <aside className="card sources-panel" aria-label="Sources panel">
      <div className="tabs" role="tablist">
        <button type="button" role="tab" aria-selected={tab === 'sources'} className={`tab${tab === 'sources' ? ' active' : ''}`} onClick={() => onTab('sources')}>
          Sources <span className="tab-count">{Object.keys(trials).length}</span>
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'viewer'}
          className={`tab${tab === 'viewer' ? ' active' : ''}`}
          disabled={viewing === null}
          onClick={() => onTab('viewer')}
        >
          Viewer <span className="tab-count">{viewing === null ? 0 : 1}</span>
        </button>
      </div>
      <div className="sources-body" role="tabpanel">
        {tab === 'viewer' && viewing !== null ? (
          <RecordViewer key={viewing} nctId={viewing} title={trials[viewing]?.brief_title ?? viewing} citations={props.citationsFor(viewing)} />
        ) : (
          <SourceList {...props} />
        )}
      </div>
    </aside>
  )
}

function SourceList({ trials, selection, onClearSelection, onHover, onOpen }: Props) {
  const [shown, setShown] = useState(PAGE)
  const numbers = trialNumbers(trials)
  const ids = selection
    ? [...selection.nctIds].sort((a, b) => (numbers.get(a) ?? 0) - (numbers.get(b) ?? 0))
    : [...numbers.keys()]
  const visible = ids.slice(0, shown)
  const remaining = ids.length - visible.length

  return (
    <>
      {selection ? (
        <div className="sources-filter">
          <h3>
            {selection.label} · {count(selection.nctIds.length)}
          </h3>
          <Markers ids={ids} numbers={numbers} />
          <button type="button" className="link-button" onClick={onClearSelection}>
            Show all sources
          </button>
        </div>
      ) : (
        <p className="sources-hint">
          Click a bar, point, node or edge to see the trials behind it. Open a source to see its record.
        </p>
      )}
      <ul className="source-list" aria-label="Sources">
        {visible.map((nctId) => (
          <TrialCard
            key={nctId}
            nctId={nctId}
            number={numbers.get(nctId) ?? 0}
            trial={trials[nctId]}
            citations={selection ? selection.citations.filter((c) => c.nct_id === nctId) : null}
            onHover={onHover}
            onOpen={onOpen}
          />
        ))}
      </ul>
      {remaining > 0 && (
        <button type="button" className="button-ghost show-more" onClick={() => setShown((n) => n + PAGE)}>
          Show {Math.min(PAGE, remaining)} more
        </button>
      )}
    </>
  )
}

const MARKERS = 3

/** The datum's first trials as numbered markers, like inline citations, each jumping to its card. */
function Markers({ ids, numbers }: { ids: string[]; numbers: Map<string, number> }) {
  const rest = ids.length - MARKERS
  return (
    <nav className="markers" aria-label="Trials in this datum">
      {ids.slice(0, MARKERS).map((nctId) => (
        <a key={nctId} href={`#source-${nctId}`} className="marker">
          [{numbers.get(nctId)}]
        </a>
      ))}
      {rest > 0 && <span className="marker-more">… +{rest}</span>}
    </nav>
  )
}

function count(n: number): string {
  return `${n} trial${n === 1 ? '' : 's'}`
}
