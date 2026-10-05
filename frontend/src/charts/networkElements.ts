// Response nodes/edges -> Cytoscape elements (SCHEMAS.md §3.6). Values are read through the
// encoding's channels (id, label, group, size; source, target, weight), never by column name.
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

/** Indexes of the nodes that keep a permanent label: the `count` largest (ties by data order) and
 *  the anchor. The rest show theirs on hover or selection, so a dense graph stays legible. */
export function labelledNodes(nodes: readonly { size: number }[], count: number, anchorIndex?: number): Set<number> {
  const order = nodes.map((node, index) => ({ size: node.size, index })).sort((a, b) => b.size - a.size || a.index - b.index)
  const labelled = new Set(order.slice(0, count).map((n) => n.index))
  if (anchorIndex !== undefined) labelled.add(anchorIndex)
  return labelled
}
