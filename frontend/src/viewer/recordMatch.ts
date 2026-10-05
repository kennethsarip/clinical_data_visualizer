// Locates a citation in its cached record (SCHEMAS.md §2, §6). Paths are under `protocolSection`
// and descend through lists, e.g. `contactsLocationsModule.locations.country`.
//
// The backend's excerpt check allows a substring for free-text fields, but every aggregator cites
// a whole value (app/aggregators), so the viewer requires equality. That is stricter: it can only
// over-report a changed record, never highlight the wrong text.

export interface Citation {
  nct_id: string
  field: string
  excerpt: string | null
}

export type CitationMatch =
  | { status: 'found'; paths: string[] } // concrete paths, e.g. `designModule.phases.1`
  | { status: 'absent' } // a null excerpt, and the field is still absent
  | { status: 'changed'; message: string } // the record no longer supports the citation

export function matchCitation(record: unknown, citation: Citation): CitationMatch {
  const section = (record as { protocolSection?: unknown } | null)?.protocolSection
  const values = valuesAt(section, citation.field.split('.'), [])
  if (citation.excerpt === null) {
    return values.length === 0
      ? { status: 'absent' }
      : {
          status: 'changed',
          message: `${citation.field} was absent when this answer was checked, but the cached record now has it.`,
        }
  }
  const paths = values.filter((v) => String(v.value) === citation.excerpt).map((v) => v.path)
  return paths.length > 0
    ? { status: 'found', paths }
    : { status: 'changed', message: `${citation.field} no longer contains "${citation.excerpt}".` }
}

interface Located {
  path: string
  value: unknown
}

/** Every scalar at `keys`, descending through lists, with the concrete path to each. */
function valuesAt(node: unknown, keys: string[], at: string[]): Located[] {
  if (Array.isArray(node)) return node.flatMap((item, index) => valuesAt(item, keys, [...at, String(index)]))
  if (keys.length === 0) return node === null || node === undefined || typeof node === 'object' ? [] : [{ path: at.join('.'), value: node }]
  if (node === null || typeof node !== 'object') return []
  const [key, ...rest] = keys
  return valuesAt((node as Record<string, unknown>)[key], rest, [...at, key])
}
