// The only module that calls the backend. Every HTTP outcome becomes one `ApiResult` kind, so
// views switch on `kind` instead of catching errors (SCHEMAS.md §1, §6). A cancel is the one
// exception: it rethrows the AbortError, because a cancelled request is not a failure to show.
import type { components, paths } from './types'

type Schemas = components['schemas']

export type VisualizeRequest = Schemas['VisualizeRequest']
export type VisualizeResponse =
  paths['/api/visualize']['post']['responses'][200]['content']['application/json']
export type StoredTrial = Schemas['StoredTrial']

export interface FieldError {
  loc: (string | number)[]
  msg: string
}

export type ApiResult<T> =
  | { kind: 'ok'; data: T }
  | { kind: 'invalid'; errors: FieldError[] } // 422: the request failed validation
  | { kind: 'not_found'; detail: string } // 404: the trial is not in the cache
  | { kind: 'unavailable'; detail: string } // 502: a dependency is down; a retry may succeed
  | { kind: 'failed'; detail: string } // unreachable server or an undocumented status

export function visualize(
  request: VisualizeRequest,
  signal?: AbortSignal,
): Promise<ApiResult<VisualizeResponse>> {
  return call<VisualizeResponse>('/api/visualize', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
    signal,
  })
}

export function getTrial(nctId: string, signal?: AbortSignal): Promise<ApiResult<StoredTrial>> {
  return call<StoredTrial>(`/api/trials/${encodeURIComponent(nctId)}`, { signal })
}

async function call<T>(url: string, init: RequestInit): Promise<ApiResult<T>> {
  let response: Response
  try {
    response = await fetch(url, init)
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    return { kind: 'failed', detail: 'Could not reach the server. Is the backend running?' }
  }
  const body = await readJson(response)
  switch (response.status) {
    case 200:
      return { kind: 'ok', data: body as T }
    case 422:
      return { kind: 'invalid', errors: fieldErrors(body) }
    case 404:
      return { kind: 'not_found', detail: detail(body) }
    case 502:
      return { kind: 'unavailable', detail: detail(body) }
    default:
      return {
        kind: 'failed',
        detail: `Unexpected response from the server (HTTP ${response.status}).`,
      }
  }
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json()
  } catch {
    return null // a proxy error page or an empty body; the status still decides the kind
  }
}

function detail(body: unknown): string {
  const value = (body as { detail?: unknown } | null)?.detail
  return typeof value === 'string' ? value : 'No detail was given.'
}

function fieldErrors(body: unknown): FieldError[] {
  const items = (body as { detail?: unknown } | null)?.detail
  if (!Array.isArray(items)) return []
  return items.map((item: { loc?: (string | number)[]; msg?: string }) => ({
    loc: item.loc ?? [],
    msg: item.msg ?? 'Invalid value.',
  }))
}
