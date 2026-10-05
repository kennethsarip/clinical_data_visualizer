import { createRef } from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { VISUALIZATION_EXAMPLES } from '../test/schemasExamples'
import { ChartView } from './ChartView'
import type { ChartHandle } from './rendererProps'
import { RENDERERS } from './renderers'
import type { Visualization } from './types'

const TYPES = ['bar_chart', 'grouped_bar_chart', 'time_series', 'scatter_plot', 'histogram', 'network_graph']
const NONE = new Set<string>()

function example(type: string): Visualization {
  const found = VISUALIZATION_EXAMPLES.find((v) => v.type === type)
  if (!found) throw new Error(`SCHEMAS.md has no ${type} example`)
  return found
}

describe('ChartView', () => {
  it('has one renderer per viz type in the contract', () => {
    expect(Object.keys(RENDERERS).sort()).toEqual([...TYPES].sort())
  })

  it.each(TYPES)('renders the SCHEMAS.md %s example', async (type) => {
    const viz = example(type)
    const { container } = render(<ChartView visualization={viz} highlighted={NONE} onSelect={() => {}} />)
    expect(screen.getByRole('figure', { name: viz.title })).toBeInTheDocument()
    await waitFor(() =>
      expect(container.querySelector(type === 'network_graph' ? 'canvas' : 'svg')).not.toBeNull(),
    )
  })

  it('exports a chart as SVG and PNG', async () => {
    const ref = createRef<ChartHandle>()
    render(<ChartView ref={ref} visualization={example('bar_chart')} highlighted={NONE} onSelect={() => {}} />)
    await waitFor(() => expect(ref.current?.ready()).toBe(true))
    expect(await ref.current!.toSVG!()).toContain('<svg')
    expect(await ref.current!.toPNG()).toMatch(/^data:image\/png/)
  })

  it('exports a network as PNG only', async () => {
    const ref = createRef<ChartHandle>()
    render(<ChartView ref={ref} visualization={example('network_graph')} highlighted={NONE} onSelect={() => {}} />)
    await waitFor(() => expect(ref.current?.ready()).toBe(true))
    expect(ref.current!.toSVG).toBeNull()
    expect(await ref.current!.toPNG()).toMatch(/^data:image\/png/)
  })
})
