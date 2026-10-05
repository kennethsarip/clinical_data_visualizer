import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { components } from '../api/types'
import { exampleWith } from '../test/schemasExamples'
import { HowAnswered } from './HowAnswered'

type OkMeta = components['schemas']['OkMeta']
const META = exampleWith((r) => r.status === 'ok').meta as OkMeta

async function open(meta: OkMeta) {
  render(<HowAnswered meta={meta} />)
  await userEvent.click(screen.getByText('How this was answered'))
  return screen.getByRole('group', { name: 'How this was answered' })
}

describe('HowAnswered (SCHEMAS.md §4 meta)', () => {
  it('starts collapsed', () => {
    render(<HowAnswered meta={META} />)
    expect(screen.getByRole('group', { name: 'How this was answered' })).not.toHaveAttribute('open')
  })

  it('shows the interpretation, filters, assumptions and notes', async () => {
    const drawer = await open(META)
    expect(within(drawer).getByText('Distribution by phase')).toBeInTheDocument()
    expect(within(drawer).getByText('Drug: Pembrolizumab')).toBeInTheDocument()
    expect(within(drawer).getByText(/A trial registered under two phases is its own category/)).toBeInTheDocument()
    expect(within(drawer).getByText('Counts every trial that mentions pembrolizumab as an intervention.')).toBeInTheDocument()
  })

  it('describes the data: sample, order, citation cap and exclusions', async () => {
    const drawer = await open(META)
    expect(within(drawer).getByText('Charted all 4 matching trials.')).toBeInTheDocument()
    expect(within(drawer).getByText('Rows in the standard phase order.')).toBeInTheDocument()
    expect(within(drawer).getByText(/cites up to 25 trials/)).toBeInTheDocument()
    expect(within(drawer).getByText('No trials were excluded.')).toBeInTheDocument()
  })

  it('shows the verification ledger, one line per step with what it verified', async () => {
    const drawer = await open(META)
    const ledger = within(drawer).getByRole('list', { name: 'Verification' })
    const steps = within(ledger).getAllByRole('listitem')
    expect(steps).toHaveLength(8)
    expect(steps[4]).toHaveTextContent('aggregation')
    expect(steps[4]).toHaveTextContent('4 / 4')
    expect(steps[4]).toHaveTextContent('All 4 trials accounted for')
    expect(steps[5]).toHaveTextContent('5 citations verified')
  })

  it('lists excluded trials by reason, with their IDs', async () => {
    const meta = {
      ...META,
      excluded: [{ rule: 'outside the country filter', count: 2, nct_ids: ['NCT00000009', 'NCT00000008'] }],
    } as OkMeta
    const drawer = await open(meta)
    const reason = within(drawer).getByText('outside the country filter: 2 trials')
    await userEvent.click(reason)
    expect(within(drawer).getByText('NCT00000009, NCT00000008')).toBeInTheDocument()
  })

  it('lists every check the answer passed', async () => {
    const drawer = await open(META)
    const checks = within(drawer).getByRole('list', { name: 'Checks passed' })
    const items = within(checks).getAllByRole('listitem')
    expect(items).toHaveLength(15) // CLAUDE.md §7.6: + conformance (6.4); membership, coverage, summaries, accounting, recount (7)
    expect(items[0]).toHaveTextContent('schema: The response matches the documented schema.')
    expect(items[9]).toHaveTextContent('conformance: Every charted trial meets each exact filter')
  })

  it('flags a capped sample and inferred filters, even while collapsed', async () => {
    const meta = {
      ...META,
      filters: { stated: { drug_name: 'Pembrolizumab' }, inferred: { overall_status: 'RECRUITING' } },
      sample: [{ cohort: 'Pembrolizumab', fetched: 2000, total: 2968, capped: true }],
    } as OkMeta
    render(<HowAnswered meta={meta} />)
    const summary = screen.getByText('How this was answered').closest('summary')!
    expect(summary).toHaveTextContent('Capped sample')
    expect(summary).toHaveTextContent('Inferred filter')
    await userEvent.click(screen.getByText('How this was answered'))
    expect(screen.getByText('Pembrolizumab: charted 2,000 of 2,968 matching trials (the fetch cap).')).toBeInTheDocument()
    expect(screen.getByText('Status: Recruiting').closest('li')).toHaveTextContent('inferred')
  })

  it('describes exclusions, top-N and network pruning', async () => {
    const meta = {
      ...META,
      excluded: [{ rule: 'missing start date', count: 2, nct_ids: ['NCT00000002', 'NCT00000001'] }],
      top_n: { limit: 20, categories_total: 63 },
      pruning: { min_edge_weight: 2, top_n_nodes: 50, fallback_used: false, nodes_removed: 12, edges_removed: 40 },
    } as OkMeta
    const drawer = await open(meta)
    expect(within(drawer).getByText('missing start date: 2 trials')).toBeInTheDocument()
    expect(within(drawer).getByText('Showing the top 20 of 63 categories.')).toBeInTheDocument()
    expect(
      within(drawer).getByText(
        'Network pruned: links shared by fewer than 2 trials and all but the 50 best-connected nodes were dropped (12 nodes, 40 links removed).',
      ),
    ).toBeInTheDocument()
  })

  it('explains the pruning fallback instead of a 1-trial threshold', async () => {
    const meta = {
      ...META,
      pruning: { min_edge_weight: 1, top_n_nodes: 50, fallback_used: true, nodes_removed: 0, edges_removed: 0 },
    } as OkMeta
    const drawer = await open(meta)
    expect(
      within(drawer).getByText(
        'Network pruned: no link was shared by enough trials to pass the usual threshold, so links from a single shared trial are kept; all but the 50 best-connected nodes were dropped (0 nodes, 0 links removed).',
      ),
    ).toBeInTheDocument()
  })

  it('a comparison has no shared filters, only each cohort\'s own', async () => {
    const meta = {
      ...META,
      interpretation: {
        intent: 'comparison',
        dimension: 'phase',
        cohorts: [
          { label: 'pembrolizumab', filters: { drug_name: 'pembrolizumab' } },
          { label: 'nivolumab', filters: { drug_name: 'nivolumab' } },
        ],
      },
      filters: { stated: {}, inferred: {} },
    } as OkMeta
    const drawer = await open(meta)
    expect(within(drawer).getByText('Comparison by phase')).toBeInTheDocument()
    expect(within(drawer).getByText('pembrolizumab: Drug: pembrolizumab')).toBeInTheDocument()
    expect(within(drawer).getByText("No filters beyond each cohort's own.")).toBeInTheDocument()
  })

  it('names a network by its entity pair', async () => {
    const meta = { ...META, interpretation: { intent: 'network', dimension: 'drug_drug', cohorts: null } } as OkMeta
    const drawer = await open(meta)
    expect(within(drawer).getByText('Network: drug–drug')).toBeInTheDocument()
  })
})
