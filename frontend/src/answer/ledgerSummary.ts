import type { components } from '../api/types'

type Step = components['schemas']['VerificationStep']

/** The badge under a chart: the two numbers a reader most wants verified. */
export function ledgerSummary(steps: Step[]): string | null {
  const aggregation = steps.find((s) => s.step === 'aggregation')
  const citations = steps.find((s) => s.step === 'citations')
  if (!aggregation || !citations || aggregation.status !== 'passed') return null
  const plural = (n: number, word: string) => `${n.toLocaleString('en-US')} ${word}${n === 1 ? '' : 's'}`
  return `${plural(aggregation.verified, 'trial')} accounted for · ${plural(citations.verified, 'citation')} verified`
}
