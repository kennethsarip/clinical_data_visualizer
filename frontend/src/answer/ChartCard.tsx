import { Suspense, lazy, useState } from 'react'
import type { components } from '../api/types'
import type { ChartHandle, Selection } from '../charts/rendererProps'
import { downloadText, downloadUrl, fileName } from './download'
import { ResponseJson } from './ResponseJson'

// Vega and Cytoscape are most of the bundle; load them only once there is a chart to draw.
const ChartView = lazy(() => import('../charts/ChartView').then((m) => ({ default: m.ChartView })))

type OkResponse = components['schemas']['OkResponse']
type View = 'chart' | 'json'

interface Props {
  response: OkResponse
  highlighted: ReadonlySet<string>
  onSelect: (selection: Selection | null) => void
}

/** The chart, or the exact response behind it (to check against SCHEMAS.md), plus exports. */
export function ChartCard({ response, highlighted, onSelect }: Props) {
  const viz = response.visualization
  const [view, setView] = useState<View>('chart')
  // State, not a ref, so the export buttons appear once the lazy renderer hands over its handle.
  const [chart, setChart] = useState<ChartHandle | null>(null)

  return (
    <section className="card chart-card" aria-labelledby="chart-title">
      <div className="card-header chart-header">
        <h2 id="chart-title">{viz.title}</h2>
        <div className="chart-tools">
          {view === 'chart' && chart && <ChartExport chart={chart} title={viz.title} />}
          <div className="tabs tabs-compact" role="tablist" aria-label="Answer view">
            <ViewTab label="Chart" active={view === 'chart'} onClick={() => setView('chart')} />
            <ViewTab label="Response JSON" active={view === 'json'} onClick={() => setView('json')} />
          </div>
        </div>
      </div>
      <div className="card-body" role="tabpanel">
        {view === 'chart' ? (
          <Suspense fallback={<p className="chart-loading">Drawing the chart…</p>}>
            <ChartView visualization={viz} meta={response.meta} highlighted={highlighted} onSelect={onSelect} ref={setChart} />
          </Suspense>
        ) : (
          <ResponseJson response={response} />
        )}
      </div>
    </section>
  )
}

function ViewTab({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button type="button" role="tab" aria-selected={active} className={`tab${active ? ' active' : ''}`} onClick={onClick}>
      {label}
    </button>
  )
}

function ChartExport({ chart, title }: { chart: ChartHandle; title: string }) {
  const { toSVG } = chart
  return (
    <div className="export-buttons">
      {toSVG && (
        <button
          type="button"
          className="button-ghost button-small"
          aria-label="Download SVG"
          onClick={async () => chart.ready() && downloadText(fileName(title, 'svg'), await toSVG(), 'image/svg+xml')}
        >
          <DownloadIcon /> SVG
        </button>
      )}
      <button
        type="button"
        className="button-ghost button-small"
        aria-label="Download PNG"
        onClick={async () => chart.ready() && downloadUrl(fileName(title, 'png'), await chart.toPNG())}
      >
        <DownloadIcon /> PNG
      </button>
    </div>
  )
}

function DownloadIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <path d="M8 2v8M4.5 6.5 8 10l3.5-3.5M2.5 13.5h11" />
    </svg>
  )
}
