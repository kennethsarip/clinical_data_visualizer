import type { Ref } from 'react'
import type { AxisMeta } from './vegaSpec'

/** What a click selected: a chart row, or a network node or edge, by index into `data`. */
export type Selection = { kind: 'row' | 'node' | 'edge'; index: number }

export interface ChartHandle {
  /** True once the chart has rendered and can be exported. */
  ready: () => boolean
  /** Null where the renderer cannot produce SVG (Cytoscape draws to canvas). */
  toSVG: (() => Promise<string>) | null
  /** A PNG data URL. */
  toPNG: () => Promise<string>
}

export interface RendererProps<V> {
  visualization: V
  /** `meta.units` and `meta.grouping`, for axis titles; optional. */
  meta?: AxisMeta
  /** NCT IDs to emphasize (reverse highlight from the sources panel); empty means none. */
  highlighted: ReadonlySet<string>
  onSelect: (selection: Selection | null) => void
  ref?: Ref<ChartHandle>
}
