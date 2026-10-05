import { describe, expect, it } from 'vitest'
import { matchCitation } from './recordMatch'

// Paths and rules follow SCHEMAS.md §2: `field` is a path under protocolSection, descending
// through lists; a null excerpt means the field is absent.
const RECORD = {
  protocolSection: {
    designModule: { phases: ['PHASE1', 'PHASE2'], enrollmentInfo: { count: 120, type: 'ACTUAL' } },
    contactsLocationsModule: {
      locations: [{ country: 'Germany' }, { country: 'United States' }, { country: 'United States' }],
    },
    statusModule: { startDateStruct: { date: '2015-03' } },
  },
}

const cite = (field: string, excerpt: string | null) => ({ nct_id: 'NCT00000001', field, excerpt })

describe('matchCitation', () => {
  it('finds a code inside a list by its element path', () => {
    expect(matchCitation(RECORD, cite('designModule.phases', 'PHASE2'))).toEqual({
      status: 'found',
      paths: ['designModule.phases.1'],
    })
  })

  it('finds every list element whose field equals the excerpt', () => {
    expect(matchCitation(RECORD, cite('contactsLocationsModule.locations.country', 'United States'))).toEqual({
      status: 'found',
      paths: ['contactsLocationsModule.locations.1.country', 'contactsLocationsModule.locations.2.country'],
    })
  })

  it('matches a number by its string form', () => {
    expect(matchCitation(RECORD, cite('designModule.enrollmentInfo.count', '120'))).toEqual({
      status: 'found',
      paths: ['designModule.enrollmentInfo.count'],
    })
  })

  it('never matches part of a value, so PHASE1 cannot cite EARLY_PHASE1', () => {
    const early = { protocolSection: { designModule: { phases: ['EARLY_PHASE1'] } } }
    expect(matchCitation(early, cite('designModule.phases', 'PHASE1')).status).toBe('changed')
  })

  it('a null excerpt holds while the field is absent', () => {
    expect(matchCitation(RECORD, cite('armsInterventionsModule.interventions.name', null))).toEqual({ status: 'absent' })
  })

  it('a null excerpt for a field the record now has is a change', () => {
    expect(matchCitation(RECORD, cite('designModule.phases', null))).toEqual({
      status: 'changed',
      message: 'designModule.phases was absent when this answer was checked, but the cached record now has it.',
    })
  })

  it('an excerpt the record no longer holds is a change', () => {
    expect(matchCitation(RECORD, cite('statusModule.startDateStruct.date', '2016-01'))).toEqual({
      status: 'changed',
      message: 'statusModule.startDateStruct.date no longer contains "2016-01".',
    })
  })
})
