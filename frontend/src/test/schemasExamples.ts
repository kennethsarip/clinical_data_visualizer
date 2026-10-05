/// <reference types="node" />
// The JSON examples in SCHEMAS.md, the renderer contract. Views are tested against these, as the
// backend's contract test validates them against schemas.py, so both sides share one fixture.
// Read with fs (tests only): a Vite `?raw` import would need the whole repo root, which holds
// .env, on the dev server's allow list.
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import type { VisualizeResponse } from '../api/client'
import type { Visualization } from '../charts/types'

const schemasMd = readFileSync(resolve(__dirname, '../../../SCHEMAS.md'), 'utf8')

const blocks = [...schemasMd.matchAll(/```json\n([\s\S]*?)```/g)].map((m) => JSON.parse(m[1]) as Record<string, unknown>)

export const RESPONSE_EXAMPLES = blocks.filter((b) => 'status' in b) as VisualizeResponse[]

export function exampleWith(predicate: (r: VisualizeResponse) => boolean): VisualizeResponse {
  const found = RESPONSE_EXAMPLES.find(predicate)
  if (!found) throw new Error('No SCHEMAS.md example matches')
  return found
}

/** Every visualization in SCHEMAS.md: inside `ok` responses and the standalone §3 examples. */
export const VISUALIZATION_EXAMPLES: Visualization[] = blocks.flatMap((b) => {
  if ('encoding' in b) return [b as unknown as Visualization]
  const viz = (b as { visualization?: Visualization | null }).visualization
  return viz ? [viz] : []
})
