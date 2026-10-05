import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { exampleWith } from './test/schemasExamples'

const CLARIFY = exampleWith((r) => r.status === 'clarification_needed')

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status })
}

/** A fetch that stays pending until aborted, like a slow backend. */
function hangingFetch() {
  return vi.fn(
    (_url: string, init: RequestInit) =>
      new Promise<Response>((_resolve, reject) => {
        init.signal?.addEventListener('abort', () =>
          reject(new DOMException('The operation was aborted.', 'AbortError')),
        )
      }),
  )
}

afterEach(() => vi.unstubAllGlobals())

async function ask(user: ReturnType<typeof userEvent.setup>, question: string) {
  await user.type(screen.getByRole('textbox', { name: /ask about clinical trials/i }), question)
  await user.click(screen.getByRole('button', { name: 'Visualize' }))
}

describe('App', () => {
  it('renders the product name and the query box', () => {
    render(<App />)
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Clinical Data Visualizer')
    expect(screen.getByRole('textbox', { name: /ask about clinical trials/i })).toBeInTheDocument()
  })

  it('explains each chart type before the first question', () => {
    render(<App />)
    const guide = screen.getByRole('list', { name: 'Chart types' })
    for (const name of ['Time series', 'Bar chart', 'Grouped bar', 'Network', 'Scatter plot', 'Histogram']) {
      expect(guide).toHaveTextContent(name)
    }
  })

  it('shows loading, then the clarification; adding an anchor opens and focuses that filter', async () => {
    let resolve!: (r: Response) => void
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>((r) => (resolve = r))))
    const user = userEvent.setup()
    render(<App />)
    await ask(user, 'show me trials')
    expect(screen.getByText('Working on it')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Visualize' })).toBeDisabled()

    resolve(json(200, CLARIFY))
    await screen.findByRole('heading', { name: 'More detail needed' })
    expect(screen.queryByText('Working on it')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Add a condition' }))
    expect(screen.getByRole('button', { name: /filters/i })).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByLabelText('Condition')).toHaveFocus()
  })

  it('cancel returns to idle without an error', async () => {
    vi.stubGlobal('fetch', hangingFetch())
    const user = userEvent.setup()
    render(<App />)
    await ask(user, 'phases of melanoma trials')
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(screen.queryByText('Working on it')).not.toBeInTheDocument())
    expect(screen.queryByRole('heading', { level: 2 })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Visualize' })).toBeEnabled()
  })

  it('retry after a 502 resends the same request', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(json(502, { detail: 'ClinicalTrials.gov: HTTP 503' }))
      .mockResolvedValueOnce(json(200, CLARIFY))
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<App />)
    await ask(user, 'phases of melanoma trials')
    await user.click(await screen.findByRole('button', { name: 'Try again' }))
    await screen.findByRole('heading', { name: 'More detail needed' })
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(fetchMock.mock.calls[1][1].body).toBe(fetchMock.mock.calls[0][1].body)
  })
})
