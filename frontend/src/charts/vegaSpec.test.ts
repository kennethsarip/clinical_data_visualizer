import { describe, expect, it } from 'vitest'
import type { ChartVisualization } from './types'
import { axisTitle, toVegaLite } from './vegaSpec'

// Expectations follow SCHEMAS.md §3: rows render in the order given, every channel names its own
// field, years are integers, a log axis pins enrollment 0 to its floor.
const row = (fields: Record<string, unknown>, ids: string[] = []) => ({
  ...fields,
  trial_count: ids.length,
  nct_ids: ids,
  citations: [],
})

function chart(type: ChartVisualization['type'], encoding: ChartVisualization['encoding'], data: object[]): ChartVisualization {
  return { type, title: 't', encoding, data } as ChartVisualization
}

const COUNT = { field: 'trial_count', type: 'quantitative' } as const

describe('toVegaLite', () => {
  it('bar chart: category on the vertical axis, data order kept, rows indexed', () => {
    const spec = toVegaLite(
      chart('bar_chart', { x: { field: 'country', type: 'nominal' }, y: COUNT } as never, [
        row({ country: 'Germany' }, ['NCT00000002', 'NCT00000001']),
        row({ country: 'Iceland' }, ['NCT00000003']),
      ]),
    )
    expect(spec.mark).toMatchObject({ type: 'bar' })
    expect(spec.encoding?.y).toMatchObject({ field: 'country', type: 'nominal', sort: null })
    expect(spec.encoding?.x).toMatchObject({ field: 'trial_count', type: 'quantitative' })
    expect((spec.data as { values: { country: string; __row: number }[] }).values.map((v) => [v.country, v.__row])).toEqual([
      ['Germany', 0],
      ['Iceland', 1],
    ])
  })

  it('grouped bar chart: series is colour and offset', () => {
    const spec = toVegaLite(
      chart('grouped_bar_chart', { x: { field: 'phase', type: 'nominal' }, y: COUNT, series: { field: 'cohort', type: 'nominal' } } as never, [
        row({ phase: 'Phase 2', cohort: 'A' }),
        row({ phase: 'Phase 2', cohort: 'B' }, ['NCT00000005']),
      ]),
    )
    expect(spec.encoding?.color).toMatchObject({ field: 'cohort', type: 'nominal', scale: { domain: ['A', 'B'] } })
    expect(spec.encoding?.yOffset).toMatchObject({ field: 'cohort', sort: null })
  })

  it('time series: integer years become dates on a yearly temporal axis', () => {
    const spec = toVegaLite(
      chart('time_series', { x: { field: 'start_year', type: 'temporal' }, y: COUNT } as never, [
        row({ start_year: 2015 }, ['NCT00000001']),
        row({ start_year: 2016 }),
      ]),
    )
    expect(spec.mark).toMatchObject({ type: 'line', point: true })
    expect(spec.transform).toContainEqual({ calculate: 'datetime(datum["start_year"], 0, 1)', as: '__x' })
    expect(spec.encoding?.x).toMatchObject({ field: '__x', type: 'temporal', timeUnit: 'year' })
  })

  it('scatter: log axis floored at 1 with enrollment 0 pinned there; colour by series', () => {
    const spec = toVegaLite(
      chart(
        'scatter_plot',
        {
          x: { field: 'start_date', type: 'temporal' },
          y: { field: 'enrollment', type: 'quantitative', scale: 'log' },
          series: { field: 'enrollment_type', type: 'nominal' },
        } as never,
        [row({ start_date: '2015-03', enrollment: 0, enrollment_type: 'Actual' }, ['NCT00000001'])],
      ),
    )
    expect(spec.mark).toMatchObject({ type: 'point' })
    expect(spec.transform).toContainEqual({ calculate: 'max(datum["enrollment"], 1)', as: '__y' })
    expect(spec.encoding?.y).toMatchObject({ field: '__y', scale: { type: 'log', domainMin: 1 } })
    expect(spec.encoding?.x).toMatchObject({ field: 'start_date', type: 'temporal' })
    expect(spec.encoding?.color).toMatchObject({ field: 'enrollment_type' })
  })

  it('histogram: ordinal bins in data order, series side by side', () => {
    const spec = toVegaLite(
      chart(
        'histogram',
        { x: { field: 'bin_label', type: 'ordinal' }, y: COUNT, series: { field: 'enrollment_type', type: 'nominal' } } as never,
        [row({ bin_label: '10-49', enrollment_type: 'Actual' }), row({ bin_label: '5000+', enrollment_type: 'Actual' })],
      ),
    )
    expect(spec.mark).toMatchObject({ type: 'bar' })
    expect(spec.encoding?.x).toMatchObject({ field: 'bin_label', type: 'ordinal', sort: null })
    expect(spec.encoding?.xOffset).toMatchObject({ field: 'enrollment_type' })
  })

  it('highlight: a param of row indexes dims every other row', () => {
    const spec = toVegaLite(
      chart('bar_chart', { x: { field: 'phase', type: 'nominal' }, y: COUNT } as never, [row({ phase: 'Phase 3' })]),
    )
    expect(spec.params).toContainEqual({ name: 'highlight', value: [] })
    expect(spec.encoding?.opacity).toEqual({
      condition: { test: 'length(highlight) == 0 || indexof(highlight, datum.__row) >= 0', value: 1 },
      value: 0.25,
    })
  })

  it('tooltip lists every encoded field, labelled as in the encoding', () => {
    const spec = toVegaLite(
      chart('bar_chart', { x: { field: 'phase', type: 'nominal' }, y: COUNT } as never, [row({ phase: 'Phase 3' })]),
    )
    expect(spec.encoding?.tooltip).toEqual([
      { field: 'phase', type: 'nominal', title: 'Phase' },
      { field: 'trial_count', type: 'quantitative', title: 'Trial count' },
    ])
  })
})

describe('axisTitle (from meta.units and meta.grouping, SCHEMAS.md §4)', () => {
  const meta = { units: { trial_count: 'trials', enrollment: 'participants' }, grouping: { dimension: 'enrollment', series: 'enrollment_type' } }

  it('adds the unit unless the name already says it', () => {
    expect(axisTitle('enrollment', meta)).toBe('Enrollment (participants)')
    expect(axisTitle('trial_count', meta)).toBe('Trial count')
  })

  it('titles a *_label category by its grouping dimension', () => {
    expect(axisTitle('bin_label', meta)).toBe('Enrollment (participants)')
  })

  it('falls back to the humanized field without meta', () => {
    expect(axisTitle('start_year')).toBe('Start year')
    expect(axisTitle('bin_label')).toBe('Bin label')
  })
})

describe('axes', () => {
  it('caps quantitative ticks so a count axis is readable', () => {
    const spec = toVegaLite(chart('bar_chart', { x: { field: 'phase', type: 'nominal' }, y: COUNT } as never, [row({ phase: 'Phase 3' })]))
    expect(spec.config.axisQuantitative).toMatchObject({ tickCount: 6 })
  })
})

describe('series colours', () => {
  it('order series by row count, ties by first appearance, so colours match across charts', () => {
    const spec = toVegaLite(
      chart(
        'scatter_plot',
        {
          x: { field: 'start_date', type: 'temporal' },
          y: { field: 'enrollment', type: 'quantitative', scale: 'log' },
          series: { field: 'enrollment_type', type: 'nominal' },
        } as never,
        [
          row({ start_date: '1980', enrollment: 5, enrollment_type: 'Type not reported' }),
          row({ start_date: '2001', enrollment: 5, enrollment_type: 'Estimated' }),
          row({ start_date: '2002', enrollment: 5, enrollment_type: 'Actual' }),
          row({ start_date: '2003', enrollment: 5, enrollment_type: 'Actual' }),
        ],
      ),
    )
    expect((spec.encoding.color as { scale: { domain: string[] } }).scale.domain).toEqual([
      'Actual',
      'Type not reported',
      'Estimated',
    ])
  })
})

describe('log axis', () => {
  it('ticks only at powers of ten up to the data maximum', () => {
    const spec = toVegaLite(
      chart(
        'scatter_plot',
        { x: { field: 'start_date', type: 'temporal' }, y: { field: 'enrollment', type: 'quantitative', scale: 'log' } } as never,
        [row({ start_date: '2015', enrollment: 0 }), row({ start_date: '2016', enrollment: 25000 })],
      ),
    )
    expect((spec.encoding.y as { axis: { values: number[] } }).axis.values).toEqual([1, 10, 100, 1000, 10000, 100000])
  })
})
