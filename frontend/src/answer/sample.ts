import type { components } from '../api/types'
import { count } from '../format'

type SampleEntry = components['schemas']['SampleEntry']

const LOWER = 'so they are lower than the registry totals'

/** One line saying the chart counts a capped sample (meta.sample), or null when nothing was
 *  capped. Bar heights are sample counts, so without this they read as registry totals. */
export function cappedNotice(sample: readonly SampleEntry[]): string | null {
  const capped = sample.filter((entry) => entry.capped)
  if (capped.length === 0) return null
  if (sample.length === 1) {
    const [{ fetched, total }] = capped
    return `Counts come from ${count(fetched)} of ${count(total)} matching trials (the fetch cap), ${LOWER}.`
  }
  const cohorts = capped.map((entry) => `${entry.cohort} ${count(entry.fetched)} of ${count(entry.total)}`)
  return `Counts come from capped samples (the fetch cap), ${LOWER}: ${cohorts.join('; ')}.`
}
