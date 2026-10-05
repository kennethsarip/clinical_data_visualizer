/** Indexes of the rows (bars, points, nodes, edges) holding any highlighted trial. Empty means
 *  "nothing highlighted", which renderers show as every row at full opacity. */
export function highlightedIndexes(rows: readonly { nct_ids: readonly string[] }[], highlighted: ReadonlySet<string>): number[] {
  if (highlighted.size === 0) return []
  return rows.flatMap((row, index) => (row.nct_ids.some((id) => highlighted.has(id)) ? [index] : []))
}
