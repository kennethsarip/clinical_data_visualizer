import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { RendererProps } from '../charts/rendererProps'
import type { Visualization } from '../charts/types'
import { exampleWith } from '../test/schemasExamples'
import { Answer } from './Answer'

// A stand-in renderer: real Vega/Cytoscape clicks need a browser (checked live instead).
vi.mock('../charts/ChartView', () => ({
  ChartView: ({ highlighted, onSelect }: RendererProps<Visualization>) => (
    <div>
      <button onClick={() => onSelect({ kind: 'row', index: 1 })}>select row 1</button>
      <button onClick={() => onSelect(null)}>click background</button>
      <output aria-label="highlighted">{[...highlighted].join(',')}</output>
    </div>
  ),
}))

afterEach(() => vi.unstubAllGlobals())

const BAR = exampleWith((r) => r.status === 'ok' && r.visualization?.type === 'bar_chart')

describe('Answer', () => {
  it('shows the filters applied above the chart, read-only, inferred ones marked', () => {
    const response = structuredClone(BAR) as never as { meta: { filters: object } }
    response.meta.filters = { stated: { drug_name: 'Pembrolizumab' }, inferred: { country: 'South Korea' } }
    render(<Answer response={response as never} />)
    const chips = screen.getByRole('list', { name: 'Filters applied' })
    expect(within(chips).getAllByRole('listitem').map((li) => li.textContent)).toEqual([
      'Drug: Pembrolizumab',
      'Country: South Korea inferred',
    ])
    expect(within(chips).queryByRole('button')).not.toBeInTheDocument()
    expect(within(chips).queryByRole('textbox')).not.toBeInTheDocument()
    const chart = screen.getByRole('heading', { name: 'Trials by Phase for Pembrolizumab' })
    expect(chips.compareDocumentPosition(chart) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })


  it('a badge under the chart sums up verification and opens the ledger', async () => {
    const user = userEvent.setup()
    render(<Answer response={BAR as never} />)
    const badge = screen.getByRole('button', { name: '4 trials accounted for · 5 citations verified' })
    const drawer = screen.getByRole('group', { name: 'How this was answered' })
    expect(drawer).not.toHaveAttribute('open')
    await user.click(badge)
    expect(drawer).toHaveAttribute('open')
  })

  it('shows the chart title and every source', async () => {
    render(<Answer response={BAR as never} />)
    expect(screen.getByRole('heading', { name: 'Trials by Phase for Pembrolizumab' })).toBeInTheDocument()
    expect(await screen.findByText('select row 1')).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /Sources\s*4/ })).toBeInTheDocument()
  })

  it('a click filters the sources and keeps that datum highlighted; background clears it', async () => {
    const user = userEvent.setup()
    render(<Answer response={BAR as never} />)
    await user.click(await screen.findByText('select row 1'))
    expect(screen.getByRole('heading', { name: 'Phase 3 · 2 trials' })).toBeInTheDocument()
    expect(screen.getByLabelText('highlighted')).toHaveTextContent('NCT00000002,NCT00000001')
    await user.click(screen.getByText('click background'))
    expect(screen.queryByRole('heading', { name: /Phase 3/ })).not.toBeInTheDocument()
    expect(screen.getByLabelText('highlighted')).toHaveTextContent('')
  })

  it('hovering a source highlights its trial on the chart', async () => {
    const user = userEvent.setup()
    render(<Answer response={BAR as never} />)
    await screen.findByText('select row 1')
    await user.hover(screen.getByText('Pembrolizumab Plus Lenvatinib in Solid Tumors'))
    expect(screen.getByLabelText('highlighted')).toHaveTextContent('NCT00000003')
    await user.unhover(screen.getByText('Pembrolizumab Plus Lenvatinib in Solid Tumors'))
    expect(screen.getByLabelText('highlighted')).toHaveTextContent('')
  })
})

describe('Answer viewer', () => {
  it('a card opens its cached record with the selected datum\'s excerpt highlighted; a new click returns to sources', async () => {
    const record = { protocolSection: { designModule: { phases: ['PHASE3'] } } }
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ nct_id: 'NCT00000002', record, fetched_at: '2026-10-05T00:00:00Z' }), { status: 200 })))
    const user = userEvent.setup()
    render(<Answer response={BAR as never} />)
    await user.click(await screen.findByText('select row 1'))
    await user.click(screen.getByText('Pembrolizumab Versus Chemotherapy in NSCLC'))
    expect(screen.getByRole('tab', { name: /Viewer/ })).toHaveAttribute('aria-selected', 'true')
    expect(await screen.findByText('PHASE3', { selector: 'mark' })).toBeInTheDocument()

    await user.click(screen.getByText('select row 1'))
    expect(screen.getByRole('tab', { name: /Sources/ })).toHaveAttribute('aria-selected', 'true')
  })
})
