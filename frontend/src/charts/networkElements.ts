// Response nodes/edges -> Cytoscape elements (SCHEMAS.md §3.6). Values are read through the
// encoding's channels (id, label, group, size; source, target, weight), never by column name.
import { THEME } from './theme'
import type { NetworkVisualization } from './types'

export interface NodeElement {
  group: 'nodes'
  classes: string
  data: { id: string; label: string; group: string; size: number; index: number }
}

export interface EdgeElement {
  group: 'edges'
  data: { id: string; source: string; target: string; weight: number; index: number }
}

export function toCytoscapeElements(viz: NetworkVisualization): { nodes: NodeElement[]; edges: EdgeElement[] } {
  const n = viz.encoding.nodes
  const e = viz.encoding.edges
  const read = (item: object, channel: { field: string } | undefined) =>
    channel ? (item as Record<string, unknown>)[channel.field] : undefined

  const nodes = viz.data.nodes.map((node, index) => ({
    group: 'nodes' as const,
    // The anchor is in every trial, so it is de-emphasized (SCHEMAS.md §3.6).
    classes: node.is_anchor ? 'anchor' : '',
    data: {
      id: String(read(node, n.id)),
      label: String(read(node, n.label) ?? read(node, n.id)),
      group: String(read(node, n.group) ?? ''),
      size: Number(read(node, n.size) ?? 1),
      index,
    },
  }))
  const edges = viz.data.edges.map((edge, index) => ({
    group: 'edges' as const,
    data: {
      id: `edge-${index}`,
      source: String(read(edge, e.source)),
      target: String(read(edge, e.target)),
      weight: Number(read(edge, e.weight) ?? 1),
      index,
    },
  }))
  return { nodes, edges }
}

const GROUP_ORDER = ['drug', 'sponsor', 'condition']

/** The entity types present, once each, in a fixed order so the legend reads the same every time. */
export function legendGroups(nodes: readonly { group: string }[]): string[] {
  const present = [...new Set(nodes.map((node) => node.group).filter(Boolean))]
  const rank = (group: string) => (GROUP_ORDER.includes(group) ? GROUP_ORDER.indexOf(group) : GROUP_ORDER.length)
  return present.sort((a, b) => rank(a) - rank(b))
}

/** One colour per entity type; the legend under the graph names them. */
export const ENTITY_COLORS: Record<string, string> = {
  drug: THEME.series[0],
  sponsor: THEME.series[3],
  condition: THEME.series[1],
}

export function entityColor(group: string): string {
  return ENTITY_COLORS[group] ?? ENTITY_COLORS.drug
}
