// Question -> request body. The question box is the only input (CLAUDE.md §14 Phase 6 step 1):
// filtering comes from the question, and the applied filters show as chips on the answer. The
// optional request fields stay in the API for tests and the eval. The checks mirror
// VisualizeRequest (SCHEMAS.md §1) so a user sees a mistake before a round trip.
import type { VisualizeRequest } from '../api/client'

// Mirrors QUERY_MAX_LENGTH in app/schemas.py.
const QUERY_MAX_LENGTH = 1000

export interface FormErrors {
  query?: string
}

export type BuildResult =
  | { ok: true; request: VisualizeRequest }
  | { ok: false; errors: FormErrors }

export function toRequest(raw: string): BuildResult {
  const query = raw.trim()
  if (!query) return { ok: false, errors: { query: 'Enter a question.' } }
  if (query.length > QUERY_MAX_LENGTH) {
    return { ok: false, errors: { query: 'Keep the question under 1,000 characters.' } }
  }
  return { ok: true, request: { query } }
}
