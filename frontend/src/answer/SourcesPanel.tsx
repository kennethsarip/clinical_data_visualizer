import { useState } from 'react'
import type { components } from '../api/types'
import type { SelectedRow } from './selection'
import { trialNumbers } from './selection'
import { TrialCard } from './TrialCard'

export type TrialSummary = components['schemas']['TrialSummary']
export type Citation = components['schemas']['Citation']

interface Props {
  trials: Record<string, TrialSummary>
  selection: SelectedRow | null
  onClearSelection: () => void
  onHover: (nctId: string | null) => void
}

const PAGE = 25

/** The trials behind the chart (SCHEMAS.md §2 `trials`), filtered to a clicked datum. */
export function SourcesPanel({ trials, selection, onClearSelection, onHover }: Props) {
  const [shown, setShown] = useState(PAGE)
  const numbers = trialNumbers(trials)
  const ids = selection
    ? [...selection.nctIds].sort((a, b) => (numbers.get(a) ?? 0) - (numbers.get(b) ?? 0))
    : [...numbers.keys()]
  const visible = ids.slice(0, shown)
  const remaining = ids.length - visible.length

  return (
    <aside className="card sources-panel" aria-label="Sources panel">
      <div className="tabs" role="tablist">
        <button type="button" role="tab" aria-selected="true" className="tab active">
          Sources <span className="tab-count">{numbers.size}</span>
        </button>
        {/* The record viewer arrives in Phase 4 step 8. */}
        <button type="button" role="tab" aria-selected="false" className="tab" disabled>
          Viewer
        </button>
      </div>
      <div className="sources-body" role="tabpanel">
        {selection ? (
          <div className="sources-filter">
            <h3>
              {selection.label} · {count(selection.nctIds.length)}
            </h3>
            <button type="button" className="link-button" onClick={onClearSelection}>
              Show all sources
            </button>
          </div>
        ) : (
          <p className="sources-hint">Click a bar, point, node or edge to see the trials behind it and the text that places each one there.</p>
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
            />
          ))}
        </ul>
        {remaining > 0 && (
          <button type="button" className="button-ghost show-more" onClick={() => setShown((n) => n + PAGE)}>
            Show {Math.min(PAGE, remaining)} more
          </button>
        )}
      </div>
    </aside>
  )
}

function count(n: number): string {
  return `${n} trial${n === 1 ? '' : 's'}`
}
