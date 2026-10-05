import { describe, expect, it } from 'vitest'
import { toRequest } from './request'

// Rules mirror SCHEMAS.md §1 / VisualizeRequest; the server stays authoritative. The question box
// is the only input (CLAUDE.md §14 Phase 6 step 1), so a request carries the query alone.
describe('toRequest', () => {
  it('trims the question and sends nothing else', () => {
    expect(toRequest('  phases of melanoma trials ')).toEqual({ ok: true, request: { query: 'phases of melanoma trials' } })
  })

  it('rejects a blank query', () => {
    expect(toRequest('   ')).toEqual({ ok: false, errors: { query: 'Enter a question.' } })
  })

  it('rejects a query over 1000 characters after trimming', () => {
    expect(toRequest(` ${'q'.repeat(1000)} `).ok).toBe(true)
    expect(toRequest('q'.repeat(1001))).toEqual({
      ok: false,
      errors: { query: 'Keep the question under 1,000 characters.' },
    })
  })
})
