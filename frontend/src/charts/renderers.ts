import type { ComponentType } from 'react'
import { NetworkGraph } from './NetworkGraph'
import type { RendererProps } from './rendererProps'
import type { ChartVisualization, NetworkVisualization, Visualization } from './types'
import { VegaChart } from './VegaChart'

type VizFor<T extends Visualization['type']> = T extends 'network_graph' ? NetworkVisualization : ChartVisualization

/** The one dispatch point from `visualization.type` to a renderer (CLAUDE.md §14 Phase 4). A new
 *  viz type fails to typecheck here until it has a renderer. */
export const RENDERERS: { [T in Visualization['type']]: ComponentType<RendererProps<VizFor<T>>> } = {
  bar_chart: VegaChart,
  grouped_bar_chart: VegaChart,
  time_series: VegaChart,
  scatter_plot: VegaChart,
  histogram: VegaChart,
  network_graph: NetworkGraph,
}
