import { useEffect, useState } from 'react'

interface Props {
  startedAt: number // epoch ms
  query: string
  onCancel: () => void
}

// Honest progress: the backend sends no stages (a streaming contract was ruled out), so this shows
// what the request does and how long it has run, never a fake percentage.
export function LoadingView({ startedAt, query, onCancel }: Props) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [])
  const seconds = Math.max(0, Math.floor((now - startedAt) / 1000))

  return (
    <section className="loading" aria-busy="true">
      <p className="loading-query">“{query}”</p>
      <div className="loading-bar" aria-hidden="true" />
      <div role="status" className="loading-text">
        <strong>Working on it</strong>
        <span>
          Planning the query, fetching trials from ClinicalTrials.gov and checking the chart · {seconds} s
        </span>
      </div>
      <button type="button" className="link-button loading-cancel" onClick={onCancel}>
        Cancel
      </button>
    </section>
  )
}
