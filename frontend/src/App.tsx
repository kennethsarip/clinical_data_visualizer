import { useRef, useState } from 'react'
import { visualize, type ApiResult, type VisualizeRequest, type VisualizeResponse } from './api/client'
import { SearchForm, type SearchFormHandle } from './search/SearchForm'
import { LoadingView } from './status/LoadingView'
import { StatusView } from './status/StatusView'

type Outcome = ApiResult<VisualizeResponse>

export default function App() {
  const [startedAt, setStartedAt] = useState<number | null>(null) // set while a request runs
  const [outcome, setOutcome] = useState<Outcome | null>(null)
  const inFlight = useRef<AbortController | null>(null)
  const lastRequest = useRef<VisualizeRequest | null>(null)
  const form = useRef<SearchFormHandle>(null)

  async function run(request: VisualizeRequest) {
    inFlight.current?.abort()
    const controller = new AbortController()
    inFlight.current = controller
    lastRequest.current = request
    setOutcome(null)
    setStartedAt(Date.now())
    try {
      const result = await visualize(request, controller.signal)
      if (inFlight.current === controller) setOutcome(result)
    } catch (error) {
      if (!(error instanceof DOMException && error.name === 'AbortError')) throw error
    } finally {
      if (inFlight.current === controller) {
        inFlight.current = null
        setStartedAt(null)
      }
    }
  }

  function cancel() {
    inFlight.current?.abort()
    inFlight.current = null
    setStartedAt(null)
  }

  function retry() {
    if (lastRequest.current) void run(lastRequest.current)
  }

  const busy = startedAt !== null
  const chart = outcome?.kind === 'ok' && outcome.data.status === 'ok' ? outcome.data : null

  return (
    <main className="app">
      <header className="app-header">
        <h1>Trials Explorer</h1>
        <p className="app-tagline">Charts from ClinicalTrials.gov, with every bar traced to its trials.</p>
      </header>
      <SearchForm ref={form} busy={busy} onSubmit={(request) => void run(request)} />
      <div className="results">
        {busy && <LoadingView startedAt={startedAt} onCancel={cancel} />}
        {!busy && outcome && (
          <StatusView result={outcome} onRetry={retry} onAddAnchor={(anchor) => form.current?.openFilter(anchor)} />
        )}
        {/* Placeholder until the renderers land (Phase 4 step 6). */}
        {!busy && chart && <p className="result-placeholder">Chart ready ({chart.visualization.type}).</p>}
      </div>
    </main>
  )
}
