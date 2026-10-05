import { useRef, useState } from 'react'
import { visualize, type ApiResult, type VisualizeRequest, type VisualizeResponse } from './api/client'
import { SearchForm } from './search/SearchForm'

export default function App() {
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<ApiResult<VisualizeResponse> | null>(null)
  const inFlight = useRef<AbortController | null>(null)

  async function run(request: VisualizeRequest) {
    inFlight.current?.abort()
    const controller = new AbortController()
    inFlight.current = controller
    setBusy(true)
    try {
      setResult(await visualize(request, controller.signal))
    } catch (error) {
      if (!(error instanceof DOMException && error.name === 'AbortError')) throw error
    } finally {
      if (inFlight.current === controller) setBusy(false)
    }
  }

  return (
    <main className="app">
      <header className="app-header">
        <h1>Trials Explorer</h1>
        <p className="app-tagline">Charts from ClinicalTrials.gov, with every bar traced to its trials.</p>
      </header>
      <SearchForm busy={busy} onSubmit={run} />
      {/* Placeholder until the status views and renderers land (Phase 4 steps 5-6). */}
      {result && (
        <p className="result-placeholder" role="status">
          {result.kind === 'ok' ? `Status: ${result.data.status}` : `Request ${result.kind}`}
        </p>
      )}
    </main>
  )
}
