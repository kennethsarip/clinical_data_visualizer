// What a clicked datum covers: its trials, its citations and a human label. Labels are read through
// the encoding channels (x/series for charts, label for nodes), never by column name.
import type { components } from '../api/types'
import type { Selection } from '../charts/rendererProps'
import type { Channel, Visualization } from '../charts/types'

export type Citation = components['schemas']['Citation']

export interface SelectedRow {
  label: string
  nctIds: string[]
  citations: Citation[]
}

export function selectedRow(viz: Visualization, selection: Selection): SelectedRow {
  if (viz.type === 'network_graph') {
    const nodeLabel = (node: object) => String(field(node, viz.encoding.nodes.label) ?? field(node, viz.encoding.nodes.id))
    if (selection.kind === 'edge') {
      const edge = viz.data.edges[selection.index]
      const byId = new Map(viz.data.nodes.map((node) => [String(field(node, viz.encoding.nodes.id)), node]))
      const end = (id: unknown) => {
        const node = byId.get(String(id))
        return node ? nodeLabel(node) : String(id)
      }
      return {
        label: `${end(field(edge, viz.encoding.edges.source))} – ${end(field(edge, viz.encoding.edges.target))}`,
        nctIds: edge.nct_ids,
        citations: edge.citations,
      }
    }
    const node = viz.data.nodes[selection.index]
    return { label: nodeLabel(node), nctIds: node.nct_ids, citations: node.citations }
  }
  const row = viz.data[selection.index]
  const { x, series } = viz.encoding as Record<string, Channel | undefined>
  const label = [x, series]
    .filter((channel): channel is Channel => Boolean(channel))
    .map((channel) => String(field(row, channel)))
    .join(' · ')
  return { label, nctIds: row.nct_ids, citations: row.citations }
}

/** Source numbers 1..n in the order of the response's `trials` map; a card keeps its number
 *  however the list is filtered. */
export function trialNumbers(trials: Record<string, unknown>): Map<string, number> {
  return new Map(Object.keys(trials).map((nctId, index) => [nctId, index + 1]))
}

function field(item: object, channel: { field: string } | undefined): unknown {
  return channel ? (item as Record<string, unknown>)[channel.field] : undefined
}
