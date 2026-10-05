import type { ComponentType } from 'react'
import type { RendererProps } from './rendererProps'
import { RENDERERS } from './renderers'
import type { Visualization } from './types'

export function ChartView(props: RendererProps<Visualization>) {
  // RENDERERS pairs each type with the renderer for its visualization shape.
  const Renderer = RENDERERS[props.visualization.type] as ComponentType<RendererProps<Visualization>>
  return (
    <figure className="chart-figure" aria-label={props.visualization.title}>
      <Renderer {...props} />
    </figure>
  )
}
