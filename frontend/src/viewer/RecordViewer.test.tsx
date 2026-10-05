import { render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Citation } from './recordMatch'
import { RecordViewer } from './RecordViewer'

const RECORD = {
  protocolSection: {
    identificationModule: { nctId: 'NCT00000001', briefTitle: 'Pembrolizumab in Advanced Melanoma' },
    designModule: { phases: ['PHASE3'], enrollmentInfo: { count: 120, type: 'ACTUAL' } },
  },
}

function serve(status: number, body: unknown) {
  const fetchMock = vi.fn(async () => new Response(JSON.stringify(body), { status }))
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

const stored = (record: unknown) => ({ nct_id: 'NCT00000001', record, fetched_at: '2026-10-05T06:05:23Z' })
const PHASE3: Citation = { nct_id: 'NCT00000001', field: 'designModule.phases', excerpt: 'PHASE3' }

function show(citations: Citation[] = [PHASE3]) {
  render(<RecordViewer nctId="NCT00000001" title="Pembrolizumab in Advanced Melanoma" citations={citations} />)
}

afterEach(() => vi.unstubAllGlobals())

describe('RecordViewer', () => {
  it('loads the cached record and highlights the cited value in place', async () => {
    const fetchMock = serve(200, stored(RECORD))
    show()
    expect(screen.getByText(/Loading the cached record/)).toBeInTheDocument()
    const mark = await screen.findByText('PHASE3', { selector: 'mark' })
    expect(fetchMock).toHaveBeenCalledWith('/api/trials/NCT00000001', expect.anything())
    expect(mark).toHaveAttribute('data-path', 'designModule.phases.0')
    // The module holding a highlight is open; the others start collapsed.
    expect(mark.closest('details')).toHaveAttribute('open')
    expect(screen.getByText('identificationModule').closest('details')).not.toHaveAttribute('open')
  })

  it('shows where the record comes from', async () => {
    serve(200, stored(RECORD))
    show()
    await screen.findByText('PHASE3', { selector: 'mark' })
    expect(screen.getByRole('heading', { name: 'Pembrolizumab in Advanced Melanoma' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Open on ClinicalTrials.gov/ })).toHaveAttribute(
      'href',
      'https://clinicaltrials.gov/study/NCT00000001',
    )
    expect(screen.getByText(/Cached 2026-10-05/)).toBeInTheDocument()
  })

  it('lists each citation with what was found', async () => {
    serve(200, stored(RECORD))
    show([PHASE3, { nct_id: 'NCT00000001', field: 'armsInterventionsModule.interventions.name', excerpt: null }])
    await screen.findByText('PHASE3', { selector: 'mark' })
    const list = screen.getByRole('list', { name: 'Citations' })
    expect(within(list).getAllByRole('listitem').map((li) => li.textContent)).toEqual([
      'designModule.phases = PHASE3 · highlighted below',
      'armsInterventionsModule.interventions.name is not in this record, which is why the trial is counted',
    ])
  })

  it('warns instead of highlighting when the cached record has changed', async () => {
    serve(200, stored({ protocolSection: { designModule: { phases: ['PHASE2'] } } }))
    show()
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The cached record has changed since this answer was checked. designModule.phases no longer contains "PHASE3".',
    )
    expect(screen.queryByText('PHASE3', { selector: 'mark' })).not.toBeInTheDocument()
  })

  it('says when a trial counts but was not quoted (citation cap)', async () => {
    serve(200, stored(RECORD))
    show([])
    expect(await screen.findByText(/counts in this chart but is not quoted/)).toBeInTheDocument()
  })

  it('points to ClinicalTrials.gov when the record is not cached', async () => {
    serve(404, { detail: 'NCT00000001 is not in the cache.' })
    show()
    expect(await screen.findByText(/not in the cache/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Open on ClinicalTrials.gov/ })).toBeInTheDocument()
  })
})
