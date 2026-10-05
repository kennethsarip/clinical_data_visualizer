// Phase picker options. Codes and labels come from the drift-checked OpenAPI schema, where the
// backend publishes vocab.py's labels as `x-labels`, so there is no second copy to keep in sync.
import openapi from '../../openapi.json'
import type { components } from '../api/types'

type Phase = components['schemas']['Phase']

const schema = openapi.components.schemas.Phase as { enum: Phase[]; 'x-labels': Record<Phase, string> }

export const PHASE_OPTIONS: readonly { value: Phase; label: string }[] = schema.enum.map((value) => ({
  value,
  label: schema['x-labels'][value],
}))
