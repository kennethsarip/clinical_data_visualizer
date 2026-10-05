import { Suspense, lazy, useState } from 'react'
import type { Selection } from '../charts/rendererProps'
import type { Visualization } from '../charts/types'
import type { AxisMeta } from '../charts/vegaSpec'

// Vega and Cytoscape are most of the bundle; load them only once there is a chart to draw.
const ChartView = lazy(() => import('../charts/ChartView').then((m) => ({ default: m.ChartView })))

const NONE: ReadonlySet<string> = new Set()

export function ChartCard({ visualization, meta }: { visualization: Visualization; meta: AxisMeta }) {
  const [selection, setSelection] = useState<Selection | null>(null)
  const selected = selection && selectedIds(visualization, selection)

  return (
    <section className="card chart-card" aria-labelledby="chart-title">
      <div className="card-header">
        <h2 id="chart-title">{visualization.title}</h2>
      </div>
      <div className="card-body">
        <Suspense fallback={<p className="chart-loading">Drawing the chart…</p>}>
          <ChartView visualization={visualization} meta={meta} highlighted={NONE} onSelect={setSelection} />
        </Suspense>
        {/* Replaced by the sources panel (Phase 4 step 7). */}
        <p className="chart-hint" role="status">
          {selected
            ? `${selected.length} trial${selected.length === 1 ? '' : 's'} selected`
            : 'Click a bar, point, node or edge to see the trials behind it.'}
        </p>
      </div>
    </section>
  )
}

function selectedIds(viz: Visualization, selection: Selection): string[] {
  if (viz.type === 'network_graph') {
    const items = selection.kind === 'edge' ? viz.data.edges : viz.data.nodes
    return items[selection.index]?.nct_ids ?? []
  }
  return viz.data[selection.index]?.nct_ids ?? []
}
