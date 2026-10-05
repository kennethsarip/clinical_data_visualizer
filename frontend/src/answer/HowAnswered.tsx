import type { components } from '../api/types'
import { count, humanize, trials } from '../format'
import { CHECKS, filterLabel, formatFilterValue } from '../vocab'
import { FilterChips } from './FilterChips'

type Schemas = components['schemas']
type OkMeta = Schemas['OkMeta']

/** "How this was answered": everything SCHEMAS.md §4 `meta` discloses about an `ok` answer. */
export function HowAnswered({ meta }: { meta: OkMeta }) {
  const capped = meta.sample.some((entry) => entry.capped)
  const inferred = Object.keys(meta.filters.inferred).length > 0
  return (
    <details className="card how-answered" aria-label="How this was answered">
      <summary>
        <span className="how-title">How this was answered</span>
        {capped && <span className="flag flag-warn">Capped sample</span>}
        {inferred && <span className="flag flag-warn">Inferred filter</span>}
        <span className="flag">{CHECKS.length} checks passed</span>
      </summary>
      <div className="how-body">
        <Section title="Question read as">
          <p>{interpretationText(meta.interpretation)}</p>
          {meta.interpretation.cohorts && (
            <ul className="how-list">
              {meta.interpretation.cohorts.map((cohort) => (
                <li key={cohort.label}>
                  {cohort.label}: {describeFilters(cohort.filters)}
                </li>
              ))}
            </ul>
          )}
        </Section>

        <Section title="Filters">
          {Object.keys(meta.filters.stated).length + Object.keys(meta.filters.inferred).length > 0 ? (
            <FilterChips filters={meta.filters} />
          ) : (
            <p>{meta.interpretation.cohorts ? "No filters beyond each cohort's own." : 'No filters: every trial matching the question.'}</p>
          )}
        </Section>

        {meta.assumptions.length > 0 && (
          <Section title="Assumptions">
            <ul className="how-list">
              {meta.assumptions.map((assumption) => (
                <li key={assumption}>{assumption}</li>
              ))}
            </ul>
          </Section>
        )}

        {meta.notes.length > 0 && (
          <Section title="Notes">
            {meta.notes.map((note) => (
              <p key={note}>{note}</p>
            ))}
          </Section>
        )}

        <Section title="Data">
          <ul className="how-list">
            {meta.sample.map((entry) => (
              <li key={entry.cohort ?? 'all'}>{sampleText(entry)}</li>
            ))}
            <li>{sortText(meta.sort)}</li>
            {meta.top_n && (
              <li>
                Showing the top {meta.top_n.limit} of {count(meta.top_n.categories_total)} categories.
              </li>
            )}
            {meta.time_granularity && <li>Grouped by {meta.time_granularity}.</li>}
            <li>
              Each datum cites up to {meta.citation_cap} trials with an exact excerpt; its count always includes
              every trial.
            </li>
            {meta.pruning && <li>{pruningText(meta.pruning)}</li>}
          </ul>
        </Section>

        <Section title="Excluded trials">
          {meta.excluded.length === 0 ? (
            <p>No trials were excluded.</p>
          ) : (
            <ul className="how-list">
              {meta.excluded.map((exclusion) => (
                <li key={exclusion.rule}>
                  {exclusion.rule}: {trials(exclusion.count)}
                </li>
              ))}
            </ul>
          )}
        </Section>

        {meta.name_merges.length > 0 && (
          <Section title="Merged drug names">
            <ul className="how-list" aria-label="Merged drug names">
              {meta.name_merges.map((merge) => (
                <li key={merge.name}>
                  {merge.merged_names.join(', ')} charted as {merge.name}: registered as its other name in{' '}
                  {merge.evidence.map((citation) => citation.nct_id).join(', ')}.
                </li>
              ))}
            </ul>
          </Section>
        )}

        <Section title="Checks passed" wide>
          <ul className="how-checks" aria-label="Checks passed">
            {CHECKS.map((check) => (
              <li key={check.name}>
                <span className="check-mark" aria-hidden="true">
                  ✓
                </span>
                <strong>{check.name}</strong>: {check.rule}
              </li>
            ))}
          </ul>
        </Section>
      </div>
    </details>
  )
}

function Section({ title, wide, children }: { title: string; wide?: boolean; children: React.ReactNode }) {
  return (
    <section className={`how-section${wide ? ' how-wide' : ''}`}>
      <h4>{title}</h4>
      {children}
    </section>
  )
}

function interpretationText({ intent, dimension }: Schemas['Interpretation']): string {
  // A network dimension names an entity pair (`drug_drug`, `sponsor_drug`).
  if (intent === 'network') return `Network: ${dimension.replace(/_/g, '–')}`
  return `${humanize(intent)} by ${humanize(dimension).toLowerCase()}`
}

function describeFilters(values: Record<string, string | number>): string {
  return Object.entries(values)
    .map(([key, value]) => `${filterLabel(key)}: ${formatFilterValue(key, value)}`)
    .join(', ')
}

function sampleText(entry: Schemas['SampleEntry']): string {
  const prefix = entry.cohort ? `${entry.cohort}: charted` : 'Charted'
  if (entry.capped) return `${prefix} ${count(entry.fetched)} of ${count(entry.total)} matching trials (the fetch cap).`
  return `${prefix} all ${count(entry.total)} matching trial${entry.total === 1 ? '' : 's'}.`
}

function sortText(sort: Schemas['Sort']): string {
  const field = humanize(sort.field).toLowerCase()
  if (sort.order === 'canonical') return `Rows in the standard ${field} order.`
  return `Rows sorted by ${field}, ${sort.order === 'desc' ? 'highest' : 'lowest'} first.`
}

function pruningText(p: Schemas['Pruning']): string {
  const removed = `${count(p.nodes_removed)} nodes, ${count(p.edges_removed)} links removed`
  const nodes = `all but the ${p.top_n_nodes} best-connected nodes were dropped (${removed})`
  // The fallback reruns at a weight of 1 when the usual threshold would leave no links (app/aggregators/network.py).
  if (p.fallback_used) {
    return `Network pruned: no link was shared by enough trials to pass the usual threshold, so links from a single shared trial are kept; ${nodes}.`
  }
  return `Network pruned: links shared by fewer than ${p.min_edge_weight} trials and ${nodes}.`
}
