import { describe, expect, it } from 'vitest'
import type { Visualization } from '../charts/types'
import { VISUALIZATION_EXAMPLES } from '../test/schemasExamples'
import { selectedRow, trialCitations, trialNumbers } from './selection'

const example = (type: string) => VISUALIZATION_EXAMPLES.find((v) => v.type === type) as Visualization

describe('selectedRow (SCHEMAS.md §3 examples)', () => {
  it('a bar is labelled by its x value and carries its ids and citations', () => {
    const row = selectedRow(example('bar_chart'), { kind: 'row', index: 1 })
    expect(row.label).toBe('Phase 3')
    expect(row.nctIds).toEqual(['NCT00000002', 'NCT00000001'])
    expect(row.citations.map((c) => c.excerpt)).toEqual(['PHASE3', 'PHASE3'])
  })

  it('a grouped bar adds its series value', () => {
    expect(selectedRow(example('grouped_bar_chart'), { kind: 'row', index: 1 }).label).toBe('Phase 2 · Nivolumab')
  })

  it('a node is labelled by its label channel', () => {
    expect(selectedRow(example('network_graph'), { kind: 'node', index: 0 }).label).toBe('Ipilimumab')
  })

  it('an edge is labelled by both end labels', () => {
    const row = selectedRow(example('network_graph'), { kind: 'edge', index: 0 })
    expect(row.label).toBe('Ipilimumab – Pembrolizumab')
    expect(row.nctIds).toEqual(['NCT00000007'])
    expect(row.citations).toHaveLength(2)
  })
})

describe('trialNumbers', () => {
  it('numbers trials 1..n in the order of the trials map', () => {
    expect(trialNumbers({ NCT00000009: {}, NCT00000003: {}, NCT00000005: {} })).toEqual(
      new Map([
        ['NCT00000009', 1],
        ['NCT00000003', 2],
        ['NCT00000005', 3],
      ]),
    )
  })
})

describe('trialCitations', () => {
  it('collects one trial\'s citations across every datum, without duplicates', () => {
    // NCT00000007 is cited on both nodes and the edge; the edge repeats the node excerpts.
    expect(trialCitations(example('network_graph'), 'NCT00000007')).toEqual([
      // Node order (SCHEMAS.md §3.6: trial_count desc, ties by id): ipilimumab first.
      { nct_id: 'NCT00000007', excerpt: 'Ipilimumab', field: 'armsInterventionsModule.interventions.name' },
      { nct_id: 'NCT00000007', excerpt: 'Pembrolizumab (MK-3475)', field: 'armsInterventionsModule.interventions.name' },
    ])
  })

  it('is empty for a trial no datum quotes', () => {
    expect(trialCitations(example('bar_chart'), 'NCT00000099')).toEqual([])
  })
})
