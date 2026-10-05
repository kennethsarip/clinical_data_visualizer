// A cached API record as nested key/value lists, one collapsible section per protocol module.
// Keys stay as the API spells them, so they read the same as the citation field paths.

interface Props {
  section: Record<string, unknown>
  highlights: ReadonlySet<string> // concrete paths under protocolSection
}

export function RecordTree({ section, highlights }: Props) {
  return (
    <div className="record-tree">
      {Object.entries(section).map(([module, value]) => (
        <details key={module} open={hasHighlight(module, highlights)}>
          <summary>{module}</summary>
          <Node value={value} path={module} highlights={highlights} />
        </details>
      ))}
    </div>
  )
}

function Node({ value, path, highlights }: { value: unknown; path: string; highlights: ReadonlySet<string> }) {
  if (Array.isArray(value)) {
    return (
      <ol className="record-list">
        {value.map((item, index) => (
          <li key={index}>
            <Node value={item} path={`${path}.${index}`} highlights={highlights} />
          </li>
        ))}
      </ol>
    )
  }
  if (value !== null && typeof value === 'object') {
    return (
      <dl className="record-object">
        {Object.entries(value).map(([key, child]) => (
          <div key={key} className="record-entry">
            <dt>{key}</dt>
            <dd>
              <Node value={child} path={`${path}.${key}`} highlights={highlights} />
            </dd>
          </div>
        ))}
      </dl>
    )
  }
  const text = String(value)
  return highlights.has(path) ? (
    <mark data-path={path}>{text}</mark>
  ) : (
    <span data-path={path}>{text}</span>
  )
}

function hasHighlight(module: string, highlights: ReadonlySet<string>): boolean {
  for (const path of highlights) if (path === module || path.startsWith(`${module}.`)) return true
  return false
}
