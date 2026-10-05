// Response `encoding` + rows -> a Vega-Lite spec (SCHEMAS.md §3). Reads columns only through the
// encoding's channels (`x`, `y`, `series`), never by name, so any registered aggregator renders.
import { THEME } from './theme'
import type { Channel, ChartVisualization } from './types'

export interface VegaLiteSpec {
  $schema: string
  data: { values: Record<string, unknown>[] }
  params: { name: string; value: number[] }[]
  transform: Record<string, unknown>[]
  mark: Record<string, unknown>
  encoding: Record<string, unknown>
  width: 'container'
  height: number
  autosize: { type: 'fit'; contains: 'padding' }
  config: Record<string, unknown>
}

export const HIGHLIGHT_PARAM = 'highlight'
const ROW = '__row' // index into visualization.data, so a click maps back to its row
const X = '__x'
const Y = '__y'

const SERIES_COLORS = THEME.series

/** The parts of `meta` that name axes (SCHEMAS.md §4); optional, so a bare spec still renders. */
export interface AxisMeta {
  units: Record<string, string>
  grouping: { dimension: string; series?: string | null }
}

export function toVegaLite(viz: ChartVisualization, meta?: AxisMeta): VegaLiteSpec {
  const title = (field: string) => axisTitle(field, meta)
  const { x, y, series } = viz.encoding as Record<string, Channel | undefined>
  if (!x || !y) throw new Error(`${viz.type} needs x and y channels`)
  const values = viz.data.map((row, index) => ({ ...row, [ROW]: index }))
  const base = {
    $schema: 'https://vega.github.io/schema/vega-lite/v6.json',
    data: { values },
    params: [{ name: HIGHLIGHT_PARAM, value: [] as number[] }],
    width: 'container' as const,
    autosize: { type: 'fit' as const, contains: 'padding' as const },
    config: CONFIG,
  }
  const shared = {
    opacity: {
      condition: { test: `length(${HIGHLIGHT_PARAM}) == 0 || indexof(${HIGHLIGHT_PARAM}, datum.${ROW}) >= 0`, value: 1 },
      value: 0.25,
    },
    tooltip: [x, y, series]
      .filter((c): c is Channel => Boolean(c))
      .map((c) => ({ field: c.field, type: c.type, title: title(c.field) })),
    ...(series && {
      color: {
        field: series.field,
        type: series.type,
        title: title(series.field),
        scale: { domain: seriesDomain(viz.data, series.field), range: [...SERIES_COLORS] },
      },
    }),
  }

  switch (viz.type) {
    case 'bar_chart':
    case 'grouped_bar_chart':
      // Category labels (sponsors, countries) are long, so categories run down the vertical axis.
      return {
        ...base,
        height: Math.max(160, viz.data.length * (series ? 34 : 26)),
        transform: [],
        mark: { type: 'bar', cornerRadiusEnd: 3, cursor: 'pointer' },
        encoding: {
          ...shared,
          y: { field: x.field, type: x.type, sort: null, title: title(x.field), axis: { labelLimit: 220 } },
          x: { field: y.field, type: y.type, title: title(y.field) },
          ...(series && { yOffset: { field: series.field, sort: null } }),
          ...(!series && { color: { value: SERIES_COLORS[0] } }),
        },
      }
    case 'histogram':
      return {
        ...base,
        height: 300,
        transform: [],
        mark: { type: 'bar', cornerRadiusEnd: 3, cursor: 'pointer' },
        encoding: {
          ...shared,
          x: { field: x.field, type: x.type, sort: null, title: title(x.field), axis: { labelAngle: 0 } },
          y: { field: y.field, type: y.type, title: title(y.field) },
          ...(series && { xOffset: { field: series.field, sort: null } }),
          ...(!series && { color: { value: SERIES_COLORS[0] } }),
        },
      }
    case 'time_series': {
      // SCHEMAS.md §2: a temporal field is an integer year or an API date string. Vega reads a bare
      // number as epoch milliseconds, so years become dates first.
      const yearly = viz.data.some((row) => typeof (row as Record<string, unknown>)[x.field] === 'number')
      return {
        ...base,
        height: 300,
        transform: yearly ? [{ calculate: `datetime(datum[${JSON.stringify(x.field)}], 0, 1)`, as: X }] : [],
        mark: { type: 'line', point: true, color: SERIES_COLORS[0], cursor: 'pointer' },
        encoding: {
          ...shared,
          x: yearly
            ? { field: X, type: 'temporal', timeUnit: 'year', title: title(x.field), axis: { format: '%Y' } }
            : { field: x.field, type: 'temporal', title: title(x.field) },
          y: { field: y.field, type: y.type, title: title(y.field) },
        },
      }
    }
    case 'scatter_plot': {
      // A log axis cannot show 0 (real data, e.g. a withdrawn trial): pin it to the floor, 1.
      const log = y.scale === 'log'
      return {
        ...base,
        height: 340,
        transform: log ? [{ calculate: `max(datum[${JSON.stringify(y.field)}], 1)`, as: Y }] : [],
        mark: { type: 'point', filled: true, size: 40, cursor: 'pointer' },
        encoding: {
          ...shared,
          x: { field: x.field, type: x.type, title: title(x.field) },
          y: log
            ? {
                field: Y,
                type: 'quantitative',
                title: title(y.field),
                scale: { type: 'log', domainMin: 1 },
                axis: { values: powersOfTen(viz.data, y.field) },
              }
            : { field: y.field, type: y.type, title: title(y.field) },
          ...(!series && { color: { value: SERIES_COLORS[0] } }),
        },
      }
    }
  }
}

/** Series values by row count, ties by first appearance: the commonest series gets the first
 *  colour whatever the sort order, so one series keeps its colour across chart types. */
function seriesDomain(rows: readonly object[], field: string): string[] {
  const counts = new Map<string, number>()
  for (const row of rows) {
    const value = String((row as Record<string, unknown>)[field])
    counts.set(value, (counts.get(value) ?? 0) + 1)
  }
  return [...counts.keys()].sort((a, b) => counts.get(b)! - counts.get(a)!)
}

/** Log-axis ticks at 1, 10, 100, ... up to the first power at or above the largest value. */
function powersOfTen(rows: readonly object[], field: string): number[] {
  const max = Math.max(1, ...rows.map((row) => Number((row as Record<string, unknown>)[field]) || 0))
  const ticks = [1]
  while (ticks[ticks.length - 1] < max) ticks.push(ticks[ticks.length - 1] * 10)
  return ticks
}

/** An axis title from the field name plus its unit; a `*_label` category (e.g. histogram bins)
 *  is titled by the grouping dimension it labels. */
export function axisTitle(field: string, meta?: AxisMeta): string {
  if (!meta) return humanize(field)
  const dimension = meta.grouping.dimension
  const source = field.endsWith('_label') && dimension in meta.units ? dimension : field
  const name = humanize(source)
  const unit = meta.units[source]
  if (!unit) return name
  const stem = unit.toLowerCase().replace(/s$/, '')
  return name.toLowerCase().includes(stem) ? name : `${name} (${unit})`
}

export function humanize(field: string): string {
  const words = field.replace(/_/g, ' ')
  return words.charAt(0).toUpperCase() + words.slice(1)
}

const CONFIG = {
  font: THEME.font,
  background: null,
  view: { stroke: null },
  axis: {
    labelColor: THEME.text,
    titleColor: THEME.text,
    titleFontWeight: 500,
    domainColor: THEME.blueBorder,
    tickColor: THEME.blueBorder,
    gridColor: THEME.grid,
    labelFontSize: 12,
    titleFontSize: 12,
  },
  axisQuantitative: { tickCount: 6 },
  axisBand: { grid: false },
  legend: { labelColor: THEME.text, titleColor: THEME.text, labelFontSize: 12, titleFontSize: 12, orient: 'top' },
}
