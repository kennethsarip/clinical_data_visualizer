import { useEffect, useMemo, useState } from 'react'
import type { components } from '../api/types'
import { downloadText, fileName } from './download'

type OkResponse = components['schemas']['OkResponse']
type CopyState = 'idle' | 'copied' | 'failed'

const COPY_LABEL: Record<CopyState, string> = { idle: 'Copy', copied: 'Copied', failed: 'Copy failed' }

/** The response exactly as the backend sent it, so a reviewer can check it against SCHEMAS.md. */
export function ResponseJson({ response }: { response: OkResponse }) {
  const text = useMemo(() => JSON.stringify(response, null, 2), [response])
  const [copy, setCopy] = useState<CopyState>('idle')
  useEffect(() => {
    if (copy === 'idle') return
    const reset = setTimeout(() => setCopy('idle'), 2000)
    return () => clearTimeout(reset)
  }, [copy])

  return (
    <div className="response-json">
      <div className="json-actions">
        <span className="json-size">{(text.length / 1024).toFixed(1)} KB</span>
        <button
          type="button"
          className="button-ghost button-small"
          onClick={() =>
            navigator.clipboard.writeText(text).then(
              () => setCopy('copied'),
              () => setCopy('failed'),
            )
          }
        >
          {COPY_LABEL[copy]}
        </button>
        <button
          type="button"
          className="button-ghost button-small"
          onClick={() => downloadText(fileName(response.visualization.title, 'json'), text, 'application/json')}
        >
          Download JSON
        </button>
      </div>
      <pre className="json-view" aria-label="Response JSON" tabIndex={0}>
        {text}
      </pre>
    </div>
  )
}
