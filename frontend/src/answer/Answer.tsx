import { useMemo, useState } from 'react'
import type { components } from '../api/types'
import type { Selection } from '../charts/rendererProps'
import { ChartCard } from './ChartCard'
import { FilterChips } from './FilterChips'
import { HowAnswered } from './HowAnswered'
import { ledgerSummary } from './ledgerSummary'
import { selectedRow, trialCitations } from './selection'
import { SourcesPanel, type PanelTab } from './SourcesPanel'

type OkResponse = components['schemas']['OkResponse']

const NONE: ReadonlySet<string> = new Set()

/** An `ok` answer: the chart beside the trials behind it. A click filters the sources to that
 *  datum; hovering a source lights up every datum its trial contributes to. */
export function Answer({ response }: { response: OkResponse }) {
  const viz = response.visualization
  const [selection, setSelection] = useState<Selection | null>(null)
  const [hovered, setHovered] = useState<string | null>(null)
  const [tab, setTab] = useState<PanelTab>('sources')
  const [viewing, setViewing] = useState<string | null>(null)
  const [howOpen, setHowOpen] = useState(false)
  const verified = ledgerSummary(response.meta.verification)
  const row = useMemo(() => (selection ? selectedRow(viz, selection) : null), [viz, selection])
  const highlighted = useMemo(
    () => (hovered ? new Set([hovered]) : row ? new Set(row.nctIds) : NONE),
    [hovered, row],
  )

  return (
    <div className="answer">
      <div className="answer-main">
        <FilterChips filters={response.meta.filters} label="Filters applied" />
        <ChartCard
          response={response}
          highlighted={highlighted}
          onSelect={(next) => {
            // A new click asks "which trials?", so the list comes back into view.
            setSelection(next)
            setTab('sources')
          }}
        />
        {verified && (
          <button
            type="button"
            className="verified-badge"
            onClick={() => {
              setHowOpen(true)
              document.getElementById('how-answered')?.scrollIntoView?.({ behavior: 'smooth' })
            }}
          >
            {verified}
          </button>
        )}
        <HowAnswered meta={response.meta} open={howOpen} onToggle={setHowOpen} />
      </div>
      <SourcesPanel
        trials={response.trials}
        selection={row}
        tab={tab}
        viewing={viewing}
        // The selected datum's citations if it holds this trial, else every citation of the trial.
        citationsFor={(nctId) =>
          row?.nctIds.includes(nctId) ? row.citations.filter((c) => c.nct_id === nctId) : trialCitations(viz, nctId)
        }
        onTab={setTab}
        onOpen={(nctId) => {
          setViewing(nctId)
          setTab('viewer')
          setHovered(null)
        }}
        onClearSelection={() => setSelection(null)}
        onHover={setHovered}
      />
    </div>
  )
}
