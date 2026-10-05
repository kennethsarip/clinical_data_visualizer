import { describe, expect, it } from 'vitest'
import evalFile from '../../../eval/questions.json'
import { EXAMPLES } from './examples'

interface EvalQuestion {
  id: string
  question_class: string
  request: Record<string, unknown>
  expected: { status: string }
}

const questions = (evalFile as { questions: EvalQuestion[] }).questions

// CLAUDE.md §1 coverage matrix: the chips double as a coverage list.
const CLASSES = ['time_trend', 'distribution', 'comparison', 'geographic', 'network', 'numeric']

describe('example questions', () => {
  it('has exactly one chip per question class, in matrix order', () => {
    expect(EXAMPLES.map((e) => e.questionClass)).toEqual(CLASSES)
  })

  it('uses only eval questions whose expected status is ok, verbatim', () => {
    for (const example of EXAMPLES) {
      const question = questions.find((q) => q.id === example.evalId)
      expect(question, example.evalId).toBeDefined()
      expect(question!.question_class).toBe(example.questionClass)
      expect(question!.expected.status).toBe('ok')
      expect(question!.request).toEqual({ query: example.query })
    }
  })
})
