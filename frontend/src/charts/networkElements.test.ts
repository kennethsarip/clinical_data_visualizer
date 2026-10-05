import { describe, expect, it } from 'vitest'
import { ENTITY_COLORS, entityColor, legendGroups, toCytoscapeElements } from './networkElements'
import type { NetworkVisualization } from './types'

const ENCODING = {
  nodes: {
    id: { field: 'id', type: 'nominal' },
    label: { field: 'label', type: 'nominal' },
    group: { field: 'entity_type', type: 'nominal' },
    size: { field: 'trial_count', type: 'quantitative' },
  },
  edges: {
    source: { field: 'source', type: 'nominal' },
    target: { field: 'target', type: 'nominal' },
    weight: { field: 'trial_count', type: 'quantitative' },
  },
}

const node = (id: string, label: string, ids: string[], isAnchor = false) => ({
  id,
  label,
  entity_type: 'drug',
  is_anchor: isAnchor,
  trial_count: ids.length,
  nct_ids: ids,
  citations: [],
})

const VIZ = {
  type: 'network_graph',
  title: 't',
  encoding: ENCODING,
  data: {
    nodes: [node('drug:pembrolizumab', 'Pembrolizumab', ['NCT00000007', 'NCT00000008'], true), node('drug:ipilimumab', 'Ipilimumab', ['NCT00000007'])],
    edges: [{ source: 'drug:ipilimumab', target: 'drug:pembrolizumab', trial_count: 1, nct_ids: ['NCT00000007'], citations: [] }],
  },
} as unknown as NetworkVisualization

describe('toCytoscapeElements', () => {
  it('maps nodes through the encoding and marks the anchor', () => {
    const { nodes } = toCytoscapeElements(VIZ)
    expect(nodes).toEqual([
      { group: 'nodes', classes: 'anchor', data: { id: 'drug:pembrolizumab', label: 'Pembrolizumab', group: 'drug', size: 2, index: 0 } },
      { group: 'nodes', classes: '', data: { id: 'drug:ipilimumab', label: 'Ipilimumab', group: 'drug', size: 1, index: 1 } },
    ])
  })

  it('maps edges through the encoding with stable ids', () => {
    const { edges } = toCytoscapeElements(VIZ)
    expect(edges).toEqual([
      { group: 'edges', data: { id: 'edge-0', source: 'drug:ipilimumab', target: 'drug:pembrolizumab', weight: 1, index: 0 } },
    ])
  })

  it('reads ids and weights from whatever fields the encoding names', () => {
    const renamed = {
      ...VIZ,
      encoding: { ...ENCODING, nodes: { ...ENCODING.nodes, label: { field: 'id', type: 'nominal' } } },
    } as unknown as NetworkVisualization
    expect(toCytoscapeElements(renamed).nodes[1].data.label).toBe('drug:ipilimumab')
  })
})

describe('legendGroups', () => {
  it('lists each entity type present once, drugs before sponsors before conditions', () => {
    const groups = [{ group: 'condition' }, { group: 'drug' }, { group: 'condition' }, { group: 'sponsor' }]
    expect(legendGroups(groups)).toEqual(['drug', 'sponsor', 'condition'])
  })

  it('keeps an unknown entity type, after the known ones', () => {
    expect(legendGroups([{ group: 'site' }, { group: 'drug' }])).toEqual(['drug', 'site'])
  })
})

describe('entityColor', () => {
  it('gives drugs, sponsors and conditions each a different colour', () => {
    expect(new Set(['drug', 'sponsor', 'condition'].map(entityColor)).size).toBe(3)
  })

  it('falls back to the drug colour for an unknown type', () => {
    expect(entityColor('site')).toBe(ENTITY_COLORS.drug)
  })
})
