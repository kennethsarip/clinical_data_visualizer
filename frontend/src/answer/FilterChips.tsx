import type { components } from '../api/types'
import { filterLabel, formatFilterValue } from '../vocab'

type Filters = components['schemas']['Filters']

/** The filters an answer applied (SCHEMAS.md §4 `meta.filters`), read-only, inferred ones marked
 *  so filtering the user did not state is never hidden. Empty when no filter was applied. */
export function FilterChips({ filters, label }: { filters: Filters; label?: string }) {
  const stated = Object.entries(filters.stated) as [string, string | number][]
  const inferred = Object.entries(filters.inferred) as [string, string | number][]
  if (stated.length + inferred.length === 0) return null
  return (
    <ul className="pill-list" aria-label={label}>
      {stated.map(([key, value]) => (
        <li key={`s-${key}`}>
          {filterLabel(key)}: {formatFilterValue(key, value)}
        </li>
      ))}
      {inferred.map(([key, value]) => (
        <li key={`i-${key}`} className="pill-inferred">
          <span>
            {filterLabel(key)}: {formatFilterValue(key, value)}
          </span>{' '}
          <em>inferred</em>
        </li>
      ))}
    </ul>
  )
}
