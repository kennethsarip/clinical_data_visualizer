import { useEffect, useState } from 'react'

interface Props {
  startedAt: number // epoch ms
  onCancel: () => void
}

// Honest progress: the backend sends no stages (a streaming contract was ruled out), so this shows
// what the request does and how long it has run, never a fake percentage.
export function LoadingView({ startedAt, onCancel }: Props) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [])
  const seconds = Math.max(0, Math.floor((now - startedAt) / 1000))

  return (
    <section className="card status-card loading" aria-busy="true">
      <div className="card-body loading-body">
        <span className="spinner" aria-hidden="true" />
        <div role="status" className="loading-text">
          <strong>Working on it</strong>
          <span>
            Planning the query, fetching trials from ClinicalTrials.gov and checking the chart ·{' '}
            {seconds} s
          </span>
        </div>
        <button type="button" className="button-ghost" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </section>
  )
}
