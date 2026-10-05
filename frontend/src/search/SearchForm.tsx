import { useId, useImperativeHandle, useRef, useState, type FormEvent, type KeyboardEvent, type Ref } from 'react'
import type { VisualizeRequest } from '../api/client'
import { toRequest, type FormErrors } from './request'

export interface SearchFormHandle {
  /** Put the cursor back in the question, e.g. after a clarification asks for more detail. */
  focusQuery: () => void
}

interface Props {
  busy: boolean
  onSubmit: (request: VisualizeRequest) => void
  ref?: Ref<SearchFormHandle>
}

export function SearchForm({ busy, onSubmit, ref }: Props) {
  const [query, setQuery] = useState('')
  const [errors, setErrors] = useState<FormErrors>({})
  const box = useRef<HTMLTextAreaElement>(null)
  const errorId = `${useId()}-query-error`

  useImperativeHandle(ref, () => ({
    focusQuery() {
      const element = box.current
      if (!element) return
      element.focus()
      element.setSelectionRange(element.value.length, element.value.length)
    },
  }))

  function submit() {
    if (busy) return
    const result = toRequest(query)
    if (!result.ok) {
      setErrors(result.errors)
      return
    }
    setErrors({})
    onSubmit(result.request)
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    submit()
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault()
      submit()
    }
  }

  return (
    <div className="search">
      <form className="card search-card" onSubmit={handleSubmit} noValidate>
        <div className="card-body">
          <div className="query-row">
            <textarea
              ref={box}
              className="query-box"
              rows={2}
              aria-label="Ask about clinical trials"
              aria-invalid={Boolean(errors.query)}
              aria-describedby={errors.query ? errorId : undefined}
              placeholder="e.g. How has the number of pembrolizumab trials changed since 2015?"
              value={query}
              onChange={(event) => {
                setQuery(event.target.value)
                setErrors({})
              }}
              onKeyDown={handleKeyDown}
            />
            <div className="search-actions">
              <button type="submit" className="button-send" aria-label="Visualize" disabled={busy}>
                <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
                  <path
                    d="M5 12h14M13 6l6 6-6 6"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2.25"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </button>
            </div>
          </div>
          {errors.query && (
            <p className="field-error" id={errorId}>
              {errors.query}
            </p>
          )}
        </div>
      </form>
    </div>
  )
}
