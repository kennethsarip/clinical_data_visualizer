import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { Visualization } from '../charts/types'
import { exampleWith } from '../test/schemasExamples'
import { selectedRow, type SelectedRow } from './selection'
import { SourcesPanel, type TrialSummary } from './SourcesPanel'

const BAR = exampleWith((r) => r.status === 'ok' && r.visualization?.type === 'bar_chart')
const TRIALS = BAR.trials as Record<string, TrialSummary>
const VIZ = BAR.visualization as Visualization

function show(selection: SelectedRow | null = null, trials = TRIALS, viewing: string | null = null, tab: 'sources' | 'viewer' = 'sources') {
  const handlers = { onClearSelection: vi.fn(), onHover: vi.fn(), onOpen: vi.fn(), onTab: vi.fn() }
  render(
    <SourcesPanel
      trials={trials}
      selection={selection}
      tab={tab}
      viewing={viewing}
      citationsFor={() => []}
      {...handlers}
    />,
  )
  return handlers
}

// Direct children only: each card holds its own nested list of chips.
const cards = () => [...screen.getByRole('list', { name: 'Sources' }).children] as HTMLElement[]

describe('SourcesPanel', () => {
  it('lists every trial behind the chart, numbered in trials order', () => {
    show()
    expect(screen.getByRole('tab', { name: /Sources\s*4/ })).toHaveAttribute('aria-selected', 'true')
    expect(cards().map((card) => within(card).getByTestId('source-number').textContent)).toEqual(['1', '2', '3', '4'])
  })

  it('shows each trial with its link, title and chips', () => {
    show()
    const first = cards()[0]
    expect(within(first).getByRole('link', { name: 'NCT00000001' })).toHaveAttribute(
      'href',
      'https://clinicaltrials.gov/study/NCT00000001',
    )
    expect(within(first).getByText('Pembrolizumab in Advanced Melanoma')).toBeInTheDocument()
    for (const chip of ['Completed', 'Phase 3', '2015-03', 'Merck Sharp & Dohme LLC', 'Melanoma']) {
      expect(within(first).getByText(chip)).toBeInTheDocument()
    }
  })

  it('filters to a selected datum, keeps source numbers, and shows each excerpt with its field', () => {
    show(selectedRow(VIZ, { kind: 'row', index: 1 }))
    expect(screen.getByRole('heading', { name: 'Phase 3 · 2 trials' })).toBeInTheDocument()
    expect(cards().map((card) => within(card).getByTestId('source-number').textContent)).toEqual(['1', '2'])
    const excerpt = within(cards()[0]).getByTestId('excerpt')
    expect(excerpt).toHaveTextContent('designModule.phases')
    expect(within(excerpt).getByText('PHASE3').tagName).toBe('MARK')
  })

  it('says when the cited field is absent from the record', () => {
    show(selectedRow(VIZ, { kind: 'row', index: 2 }))
    expect(within(cards()[0]).getByTestId('excerpt')).toHaveTextContent('designModule.phases is not in this record')
  })

  it('says when the citation cap left a trial without an excerpt', () => {
    const selection = { label: 'Phase 3', nctIds: ['NCT00000002', 'NCT00000001'], citations: [] }
    show(selection)
    expect(within(cards()[0]).getByTestId('excerpt')).toHaveTextContent('Not cited: each datum cites at most 25 trials')
  })

  it('clears the selection', async () => {
    const { onClearSelection } = show(selectedRow(VIZ, { kind: 'row', index: 1 }))
    await userEvent.click(screen.getByRole('button', { name: 'Show all sources' }))
    expect(onClearSelection).toHaveBeenCalledOnce()
  })

  it('reports hover and keyboard focus, for reverse highlight on the chart', async () => {
    const { onHover } = show()
    await userEvent.hover(cards()[1])
    expect(onHover).toHaveBeenLastCalledWith('NCT00000002')
    await userEvent.unhover(cards()[1])
    expect(onHover).toHaveBeenLastCalledWith(null)
  })

  it('shows 25 cards at a time', async () => {
    const many = Object.fromEntries(
      Array.from({ length: 30 }, (_, i) => [`NCT${String(i + 1).padStart(8, '0')}`, TRIALS.NCT00000001]),
    )
    show(null, many)
    expect(cards()).toHaveLength(25)
    await userEvent.click(screen.getByRole('button', { name: 'Show 5 more' }))
    expect(cards()).toHaveLength(30)
  })

  it('opens a card in the viewer on click or Enter, but not from its external link', async () => {
    const { onOpen } = show()
    await userEvent.click(within(cards()[1]).getByText('Pembrolizumab Versus Chemotherapy in NSCLC'))
    expect(onOpen).toHaveBeenLastCalledWith('NCT00000002')
    cards()[2].focus()
    await userEvent.keyboard('{Enter}')
    expect(onOpen).toHaveBeenLastCalledWith('NCT00000003')
    onOpen.mockClear()
    await userEvent.click(within(cards()[0]).getByRole('link', { name: 'NCT00000001' }))
    expect(onOpen).not.toHaveBeenCalled()
  })

  it('enables the Viewer tab once a trial is open', async () => {
    show()
    expect(screen.getByRole('tab', { name: /Viewer/ })).toBeDisabled()
  })

  it('switches tabs', async () => {
    const { onTab } = show(null, TRIALS, 'NCT00000001')
    await userEvent.click(screen.getByRole('tab', { name: /Viewer\s*1/ }))
    expect(onTab).toHaveBeenCalledWith('viewer')
  })
})
