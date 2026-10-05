import type { components } from '../api/types'

type Step = components['schemas']['VerificationStep']

const STATUS_TEXT: Record<Step['status'], string> = {
  passed: 'passed',
  stopped: 'stopped',
  failed: 'failed',
  not_reached: 'not reached',
}

/** The verification ledger (SCHEMAS.md §4 `verification`): what each pipeline step checked,
 *  how much held, and where an answer stopped. Every line is written by the backend's Python. */
export function Ledger({ steps }: { steps: Step[] }) {
  return (
    <ol className="ledger" aria-label="Verification">
      {steps.map((step) => (
        <li key={step.step} className={`ledger-step ledger-${step.status}`}>
          <span className="ledger-name">{step.step}</span>
          <span className="ledger-status">{STATUS_TEXT[step.status]}</span>
          {step.total > 0 && (
            <span className="ledger-count">
              {step.verified} / {step.total}
            </span>
          )}
          <span className="ledger-result">{step.result}</span>
          {step.checks.length > 0 && step.status !== 'not_reached' && (
            <span className="ledger-checks">{step.checks.join(' · ')}</span>
          )}
        </li>
      ))}
    </ol>
  )
}
