// Which network labels to show, and on which side of their node (CLAUDE.md §14 Phase 8.2): every
// shown label is readable, with no overlap. Labels are placed greedily in priority order (the
// anchor, then trial count, then data order). Each takes the first side, of below, above, right
// and left, that stays inside the view and clears every placed label and every other node. If no
// side is clear, it takes the first side that covers only unlabelled nodes: those are drawn under
// labelled ones (z-index), so a hub in a dense core keeps a readable label. A label never covers a
// labelled node, and a node already under a placed label gets none, since it would be drawn on top
// of that label. Zooming in makes room, so more labels appear.
// Boxes are in rendered pixels, measured by the renderer; the caller re-runs this on zoom or pan.

export interface Box {
  x1: number
  y1: number
  x2: number
  y2: number
}

export type Side = 'bottom' | 'top' | 'right' | 'left'

export interface LabelCandidate {
  index: number // the node's position in `visualization.data.nodes`
  body: Box // the node as drawn, border included
  labels: [Side, Box][] // where its label would be drawn on each side, in order of preference
  priority: number // trial count: larger wins a contested spot
  anchor: boolean
}

/** The label's box on every side, from its measured box below the node: the renderer keeps the
 *  same gap from the node on each side, so the other boxes mirror that one about the centre. */
export function sideBoxes(centre: { x: number; y: number }, bottom: Box): [Side, Box][] {
  const gap = bottom.y1 - centre.y // centre to the label's near edge
  const width = bottom.x2 - bottom.x1
  const height = bottom.y2 - bottom.y1
  const middle = { y1: centre.y - height / 2, y2: centre.y + height / 2 }
  return [
    ['bottom', bottom],
    ['top', { x1: bottom.x1, y1: centre.y - gap - height, x2: bottom.x2, y2: centre.y - gap }],
    ['right', { x1: centre.x + gap, x2: centre.x + gap + width, ...middle }],
    ['left', { x1: centre.x - gap - width, x2: centre.x - gap, ...middle }],
  ]
}

/** Node index -> the side its label is drawn on; nodes left out show no label. */
export function placeLabels(candidates: readonly LabelCandidate[], view: { width: number; height: number }): Map<number, Side> {
  const placed: Box[] = []
  const sides = new Map<number, Side>()
  for (const candidate of [...candidates].sort(byPriority)) {
    if (placed.some((label) => overlaps(candidate.body, label))) continue
    const others = candidates.filter((other) => other.index !== candidate.index)
    const free = (box: Box) => inside(box, view) && !placed.some((label) => overlaps(box, label))
    const clear = (box: Box) => free(box) && !others.some((other) => overlaps(box, other.body))
    const coversUnlabelled = (box: Box) =>
      free(box) && !others.some((other) => sides.has(other.index) && overlaps(box, other.body))
    const spot = candidate.labels.find(([, box]) => clear(box)) ?? candidate.labels.find(([, box]) => coversUnlabelled(box))
    if (spot) {
      placed.push(spot[1])
      sides.set(candidate.index, spot[0])
    }
  }
  return sides
}

function byPriority(a: LabelCandidate, b: LabelCandidate): number {
  return Number(b.anchor) - Number(a.anchor) || b.priority - a.priority || a.index - b.index
}

function overlaps(a: Box, b: Box): boolean {
  return a.x1 < b.x2 && b.x1 < a.x2 && a.y1 < b.y2 && b.y1 < a.y2
}

function inside(box: Box, view: { width: number; height: number }): boolean {
  return box.x1 >= 0 && box.y1 >= 0 && box.x2 <= view.width && box.y2 <= view.height
}
