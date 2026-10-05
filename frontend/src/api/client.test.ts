import { afterEach, describe, expect, it, vi } from 'vitest'
import { getTrial, visualize } from './client'

// Bodies follow SCHEMAS.md §1/§6 and FastAPI's 422 shape, not the client's output.
const CLARIFY = {
  status: 'clarification_needed',
  visualization: null,
  trials: {},
  meta: {
    source: 'clinicaltrials.gov',
    filters: { stated: {}, inferred: {} },
    assumptions: [],
    missing: ['drug_name', 'condition', 'sponsor'],
    notes: ['Name a drug, condition or sponsor to chart.'],
  },
}

function respond(status: number, body: unknown) {
  const fetchMock = vi.fn(async () => new Response(JSON.stringify(body), { status }))
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('visualize', () => {
  it('posts the request as JSON and returns any 200 status as ok', async () => {
    const fetchMock = respond(200, CLARIFY)
    const result = await visualize({ query: 'show me trials' })
    expect(result).toEqual({ kind: 'ok', data: CLARIFY })
    expect(fetchMock).toHaveBeenCalledWith('/api/visualize', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query: 'show me trials' }),
      signal: undefined,
    })
  })

  it('turns a 422 into field errors', async () => {
    respond(422, {
      detail: [
        { type: 'value_error', loc: ['body'], msg: 'Value error, end_year is before start_year', input: {} },
      ],
    })
    const result = await visualize({ query: 'melanoma', start_year: 2022, end_year: 2018 })
    expect(result).toEqual({
      kind: 'invalid',
      errors: [{ loc: ['body'], msg: 'Value error, end_year is before start_year' }],
    })
  })

  it('turns a 502 into unavailable with the detail', async () => {
    respond(502, { detail: 'ClinicalTrials.gov: HTTP 503' })
    expect(await visualize({ query: 'melanoma phases' })).toEqual({
      kind: 'unavailable',
      detail: 'ClinicalTrials.gov: HTTP 503',
    })
  })

  it('reports an unexpected status as failed', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('Internal Server Error', { status: 500 })))
    expect(await visualize({ query: 'melanoma phases' })).toEqual({
      kind: 'failed',
      detail: 'Unexpected response from the server (HTTP 500).',
    })
  })

  it('reports an unreachable server as failed', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Promise.reject(new TypeError('Failed to fetch'))))
    expect(await visualize({ query: 'melanoma phases' })).toEqual({
      kind: 'failed',
      detail: 'Could not reach the server. Is the backend running?',
    })
  })

  it('rethrows a cancel so the caller can ignore it', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => Promise.reject(new DOMException('The operation was aborted.', 'AbortError'))),
    )
    await expect(visualize({ query: 'melanoma phases' })).rejects.toMatchObject({ name: 'AbortError' })
  })
})

describe('getTrial', () => {
  it('fetches the cached record', async () => {
    const stored = { nct_id: 'NCT00000001', record: { protocolSection: {} }, fetched_at: '2026-10-04T12:00:00Z' }
    const fetchMock = respond(200, stored)
    expect(await getTrial('NCT00000001')).toEqual({ kind: 'ok', data: stored })
    expect(fetchMock).toHaveBeenCalledWith('/api/trials/NCT00000001', { signal: undefined })
  })

  it('turns a 404 into not_found', async () => {
    respond(404, { detail: 'NCT00000009 is not in the cache.' })
    expect(await getTrial('NCT00000009')).toEqual({
      kind: 'not_found',
      detail: 'NCT00000009 is not in the cache.',
    })
  })

  it('escapes the ID in the path', async () => {
    const fetchMock = respond(422, { detail: [] })
    await getTrial('NCT/../x')
    expect(fetchMock).toHaveBeenCalledWith('/api/trials/NCT%2F..%2Fx', { signal: undefined })
  })
})
