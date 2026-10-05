import { Suspense, lazy } from 'react'
import type { Selection } from '../charts/rendererProps'
import type { Visualization } from '../charts/types'
import type { AxisMeta } from '../charts/vegaSpec'

// Vega and Cytoscape are most of the bundle; load them only once there is a chart to draw.
const ChartView = lazy(() => import('../charts/ChartView').then((m) => ({ default: m.ChartView })))

interface Props {
  visualization: Visualization
  meta: AxisMeta
  highlighted: ReadonlySet<string>
  onSelect: (selection: Selection | null) => void
}

export function ChartCard({ visualization, meta, highlighted, onSelect }: Props) {
  return (
    <section className="card chart-card" aria-labelledby="chart-title">
      <div className="card-header">
        <h2 id="chart-title">{visualization.title}</h2>
      </div>
      <div className="card-body">
        <Suspense fallback={<p className="chart-loading">Drawing the chart…</p>}>
          <ChartView visualization={visualization} meta={meta} highlighted={highlighted} onSelect={onSelect} />
        </Suspense>
      </div>
    </section>
  )
}
