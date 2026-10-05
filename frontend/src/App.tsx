import { useRef, useState } from 'react'
import { visualize, type ApiResult, type VisualizeRequest, type VisualizeResponse } from './api/client'
import { Answer } from './answer/Answer'
import { ChartGuide } from './search/ChartGuide'
import { SearchForm, type SearchFormHandle } from './search/SearchForm'
import { LoadingView } from './status/LoadingView'
import { StatusView } from './status/StatusView'

type Outcome = ApiResult<VisualizeResponse>

export default function App() {
  const [startedAt, setStartedAt] = useState<number | null>(null) // set while a request runs
  const [outcome, setOutcome] = useState<Outcome | null>(null)
  const [asked, setAsked] = useState('') // the question in flight, echoed while loading
  const [runId, setRunId] = useState(0) // a new answer gets fresh chart state (selection)
  const inFlight = useRef<AbortController | null>(null)
  const lastRequest = useRef<VisualizeRequest | null>(null)
  const form = useRef<SearchFormHandle>(null)

  async function run(request: VisualizeRequest) {
    inFlight.current?.abort()
    const controller = new AbortController()
    inFlight.current = controller
    lastRequest.current = request
    setAsked(request.query)
    setRunId((id) => id + 1)
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
  const landing = !busy && !outcome // before the first question: a centred hero, no results area
  const chart = outcome?.kind === 'ok' && outcome.data.status === 'ok' ? outcome.data : null

  return (
    <main className={landing ? 'app landing' : 'app'}>
      <div className="topbar">
        <header className="app-header">
          <h1>Clinical Data Visualizer</h1>
          {landing && (
            <p className="app-tagline">Ask a question. Get a chart from ClinicalTrials.gov, every point cited.</p>
          )}
        </header>
        {landing && <ChartGuide />}
        <SearchForm ref={form} busy={busy} onSubmit={(request) => void run(request)} />
      </div>
      <div className="results">
        {busy && <LoadingView startedAt={startedAt} query={asked} onCancel={cancel} />}
        {!busy && outcome && (
          <StatusView result={outcome} onRetry={retry} onAddAnchor={(anchor) => form.current?.openFilter(anchor)} />
        )}
        {!busy && chart && <Answer key={runId} response={chart} />}
      </div>
    </main>
  )
}
