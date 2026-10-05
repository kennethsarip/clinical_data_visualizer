import type { components } from '../api/types'

type Schemas = components['schemas']
export type ChartVisualization = Schemas['ChartVisualization']
export type NetworkVisualization = Schemas['NetworkVisualization']
export type Visualization = ChartVisualization | NetworkVisualization
export type Channel = Schemas['Channel']
