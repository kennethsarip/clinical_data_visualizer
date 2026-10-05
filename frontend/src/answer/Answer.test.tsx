import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
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

const BAR = exampleWith((r) => r.status === 'ok' && r.visualization?.type === 'bar_chart')

describe('Answer', () => {
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
