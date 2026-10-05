import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { ApiResult, VisualizeResponse } from '../api/client'
import { exampleWith } from '../test/schemasExamples'
import { StatusView } from './StatusView'

type Meta = Record<string, unknown>
const meta = (r: VisualizeResponse) => r.meta as unknown as Meta

function show(result: ApiResult<VisualizeResponse>) {
  const onRetry = vi.fn()
  const onAddAnchor = vi.fn()
  const { container } = render(<StatusView result={result} onRetry={onRetry} onAddAnchor={onAddAnchor} />)
  return { onRetry, onAddAnchor, container }
}

const ok = (data: VisualizeResponse): ApiResult<VisualizeResponse> => ({ kind: 'ok', data })

describe('StatusView, from the SCHEMAS.md §5 examples', () => {
  it('clarification: shows the note and one add-chip per missing anchor', async () => {
    const response = exampleWith((r) => r.status === 'clarification_needed')
    const { onAddAnchor } = show(ok(response))
    expect(screen.getByRole('heading', { name: 'More detail needed' })).toBeInTheDocument()
    expect(screen.getByText('Name a drug, condition or sponsor to chart.')).toBeInTheDocument()
    const chips = screen.getByRole('group', { name: /add what the question is about/i })
    expect(within(chips).getAllByRole('button').map((b) => b.textContent)).toEqual([
      'Add a drug',
      'Add a condition',
      'Add a sponsor',
    ])
    await userEvent.click(within(chips).getByRole('button', { name: 'Add a condition' }))
    expect(onAddAnchor).toHaveBeenCalledExactlyOnceWith('condition')
  })

  it('clarification with nothing missing: shows the reason and no add-chips', () => {
    const base = exampleWith((r) => r.status === 'clarification_needed')
    const response = {
      ...base,
      meta: { ...meta(base), missing: [], notes: ['Compare at most 4 drugs, conditions or sponsors at once.'] },
    } as unknown as VisualizeResponse
    show(ok(response))
    expect(screen.getByText('Compare at most 4 drugs, conditions or sponsors at once.')).toBeInTheDocument()
    expect(screen.queryByRole('group', { name: /add what the question is about/i })).not.toBeInTheDocument()
  })

  it('no results with every entity found: lists the filters applied', () => {
    show(ok(exampleWith((r) => r.status === 'no_results' && (meta(r).not_found as string[]).length === 0)))
    expect(screen.getByRole('heading', { name: 'No matching trials' })).toBeInTheDocument()
    const filters = screen.getByRole('list', { name: 'Filters applied' })
    expect(within(filters).getAllByRole('listitem').map((li) => li.textContent)).toEqual([
      'Condition: Melanoma',
      'Phase: Phase 4',
      'Country: Iceland',
    ])
    expect(screen.getByText('No trials match all applied filters. The search was not widened.')).toBeInTheDocument()
  })

  it('not found: names the entity and says nothing was substituted', () => {
    show(ok(exampleWith((r) => r.status === 'no_results' && (meta(r).not_found as string[]).length > 0)))
    expect(screen.getByRole('heading', { name: 'Not found on ClinicalTrials.gov' })).toBeInTheDocument()
    expect(within(screen.getByRole('list', { name: 'Not found' })).getByText('Zorblaxumab')).toBeInTheDocument()
    expect(screen.getByText(/No similar drug was substituted/)).toBeInTheDocument()
  })

  it('degraded: lists each failed check with its message', () => {
    show(ok(exampleWith((r) => r.status === 'degraded')))
    expect(screen.getByRole('heading', { name: 'No verified chart' })).toBeInTheDocument()
    expect(screen.getByRole('list', { name: 'Failed checks' })).toHaveTextContent(
      "encoding: Field 'phase' is missing from row 3.",
    )
  })

  it('ok renders nothing here; the chart view owns it', () => {
    const response = exampleWith((r) => r.status === 'ok')
    const { container } = show(ok(response))
    expect(container).toBeEmptyDOMElement()
  })
})

describe('StatusView, HTTP errors', () => {
  it('422: names each rejected field', () => {
    show({
      kind: 'invalid',
      errors: [
        { loc: ['body', 'end_year'], msg: 'Input should be a valid integer' },
        { loc: ['body'], msg: 'Value error, start_year (2022) is after end_year (2018)' },
      ],
    })
    expect(screen.getByRole('heading', { name: 'The request was rejected' })).toBeInTheDocument()
    expect(screen.getAllByRole('listitem').map((li) => li.textContent)).toEqual([
      'End year: Input should be a valid integer',
      'Value error, start_year (2022) is after end_year (2018)',
    ])
  })

  it('502: says a dependency is down and offers a retry', async () => {
    const { onRetry } = show({ kind: 'unavailable', detail: 'ClinicalTrials.gov: HTTP 503' })
    expect(screen.getByRole('heading', { name: 'A data service is unavailable' })).toBeInTheDocument()
    expect(screen.getByText('ClinicalTrials.gov: HTTP 503')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(onRetry).toHaveBeenCalledOnce()
  })

  it('any other failure: shows the detail and offers a retry', async () => {
    const { onRetry } = show({ kind: 'failed', detail: 'Could not reach the server. Is the backend running?' })
    expect(screen.getByRole('heading', { name: 'Something went wrong' })).toBeInTheDocument()
    expect(screen.getByText('Could not reach the server. Is the backend running?')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(onRetry).toHaveBeenCalledOnce()
  })
})
