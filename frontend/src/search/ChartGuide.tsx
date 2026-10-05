// One line per viz type the backend can return (SCHEMAS.md), so a first-time user knows what to ask.
const CHART_TYPES: readonly { name: string; use: string }[] = [
  { name: 'Time series', use: 'How trial counts change year by year' },
  { name: 'Bar chart', use: 'Which phases, sponsors or countries lead' },
  { name: 'Grouped bar', use: 'Two drugs or conditions side by side' },
  { name: 'Network', use: 'Which drugs and sponsors share trials' },
  { name: 'Scatter plot', use: "Each trial's enrollment against its start date" },
  { name: 'Histogram', use: 'How enrollment sizes are spread' },
]

export function ChartGuide() {
  return (
    <ul className="chart-guide" aria-label="Chart types">
      {CHART_TYPES.map(({ name, use }) => (
        <li key={name}>
          <span className="chart-guide-name">{name}</span>
          <span className="chart-guide-use">{use}</span>
        </li>
      ))}
    </ul>
  )
}
