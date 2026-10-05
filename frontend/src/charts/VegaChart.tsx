import { useEffect, useImperativeHandle, useLayoutEffect, useRef } from 'react'
import embed from 'vega-embed'
import type { View } from 'vega'
import type { TopLevelSpec } from 'vega-lite'
import { highlightedIndexes } from './highlight'
import type { RendererProps } from './rendererProps'
import type { ChartVisualization } from './types'
import { HIGHLIGHT_PARAM, toVegaLite } from './vegaSpec'

export function VegaChart({ visualization, meta, highlighted, onSelect, ref }: RendererProps<ChartVisualization>) {
  const container = useRef<HTMLDivElement>(null)
  const view = useRef<View | null>(null)
  // Kept in refs so a new callback or highlight does not rebuild the chart.
  const select = useRef(onSelect)
  const highlight = useRef(highlighted)
  useLayoutEffect(() => {
    select.current = onSelect
    highlight.current = highlighted
  })

  useImperativeHandle(ref, () => ({
    ready: () => view.current !== null,
    toSVG: () => requireView(view.current).toSVG(),
    toPNG: () => requireView(view.current).toImageURL('png', 2),
  }))

  useEffect(() => {
    let cancelled = false
    const target = container.current
    if (!target) return
    const spec = toVegaLite(visualization, meta) as unknown as TopLevelSpec
    const embedding = embed(target, spec, { renderer: 'svg', actions: false, tooltip: { theme: 'light' } })
    void embedding.then((result) => {
      if (cancelled) return result.finalize()
      view.current = result.view
      result.view.addEventListener('click', (_event, item) => {
        const row = (item?.datum as { __row?: number } | undefined)?.__row
        select.current(row === undefined ? null : { kind: 'row', index: row })
      })
      void applyHighlight(result.view, visualization, highlight.current)
    })
    return () => {
      cancelled = true
      view.current = null
      void embedding.then((result) => result.finalize())
    }
  }, [visualization, meta])

  useEffect(() => {
    if (view.current) void applyHighlight(view.current, visualization, highlighted)
  }, [visualization, highlighted])

  return <div ref={container} className="vega-chart" />
}

function applyHighlight(view: View, viz: ChartVisualization, highlighted: ReadonlySet<string>) {
  return view.signal(HIGHLIGHT_PARAM, highlightedIndexes(viz.data, highlighted)).runAsync()
}

function requireView(view: View | null): View {
  if (!view) throw new Error('The chart has not rendered yet')
  return view
}
