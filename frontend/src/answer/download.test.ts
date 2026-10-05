import { describe, expect, it } from 'vitest'
import { fileName } from './download'

describe('fileName', () => {
  it('slugs the title', () => {
    expect(fileName('Drug–Drug Co-occurrence in Breast Cancer (2015+)', 'png')).toBe('drug-drug-co-occurrence-in-breast-cancer-2015.png')
  })

  it('falls back when nothing is left', () => {
    expect(fileName('—', 'json')).toBe('chart.json')
  })

  it('caps the length without a trailing dash', () => {
    const name = fileName(`${'a'.repeat(79)} b`, 'svg')
    expect(name).toBe(`${'a'.repeat(79)}.svg`)
  })
})
