import { useMemo, useState } from 'react'
import type { components } from '../api/types'
import type { Selection } from '../charts/rendererProps'
import { ChartCard } from './ChartCard'
import { selectedRow } from './selection'
import { SourcesPanel } from './SourcesPanel'

type OkResponse = components['schemas']['OkResponse']

const NONE: ReadonlySet<string> = new Set()

/** An `ok` answer: the chart beside the trials behind it. A click filters the sources to that
 *  datum; hovering a source lights up every datum its trial contributes to. */
export function Answer({ response }: { response: OkResponse }) {
  const viz = response.visualization
  const [selection, setSelection] = useState<Selection | null>(null)
  const [hovered, setHovered] = useState<string | null>(null)
  const row = useMemo(() => (selection ? selectedRow(viz, selection) : null), [viz, selection])
  const highlighted = useMemo(
    () => (hovered ? new Set([hovered]) : row ? new Set(row.nctIds) : NONE),
    [hovered, row],
  )

  return (
    <div className="answer">
      <div className="answer-main">
        <ChartCard visualization={viz} meta={response.meta} highlighted={highlighted} onSelect={setSelection} />
      </div>
      <SourcesPanel
        trials={response.trials}
        selection={row}
        onClearSelection={() => setSelection(null)}
        onHover={setHovered}
      />
    </div>
  )
}
