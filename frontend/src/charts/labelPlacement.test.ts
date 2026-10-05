import { describe, expect, it } from 'vitest'
import { type LabelCandidate, placeLabels, sideBoxes } from './labelPlacement'

// Rendered-pixel geometry, as the renderer reports it (CLAUDE.md §14 Phase 8.2: no shown label
// overlaps): a node at (x, y) with radius r has its bottom label centred below it, from y + r + 4
// to y + r + 4 + 14. sideBoxes mirrors that box to the top, right and left.
const VIEW = { width: 800, height: 600 }
const THIN = { width: 800, height: 40 } // only room beside a node

interface Spec {
  radius?: number
  width?: number
  priority?: number
  anchor?: boolean
}

const at = (index: number, x: number, y: number, { radius = 10, width = 60, priority = 0, anchor = false }: Spec = {}): LabelCandidate => {
  const top = y + radius + 4
  const bottom = { x1: x - width / 2, y1: top, x2: x + width / 2, y2: top + 14 }
  return {
    index,
    body: { x1: x - radius, y1: y - radius, x2: x + radius, y2: y + radius },
    labels: sideBoxes({ x, y }, bottom),
    priority,
    anchor,
  }
}

const place = (candidates: LabelCandidate[], view = VIEW) => Object.fromEntries(placeLabels(candidates, view))

describe('sideBoxes', () => {
  it('mirrors the bottom label to the other sides at the same distance from the centre', () => {
    const boxes = sideBoxes({ x: 100, y: 100 }, { x1: 70, y1: 114, x2: 130, y2: 128 })
    expect(boxes).toEqual([
      ['bottom', { x1: 70, y1: 114, x2: 130, y2: 128 }],
      ['top', { x1: 70, y1: 72, x2: 130, y2: 86 }],
      ['right', { x1: 114, y1: 93, x2: 174, y2: 107 }],
      ['left', { x1: 26, y1: 93, x2: 86, y2: 107 }],
    ])
  })
})

describe('placeLabels', () => {
  it('puts labels below their nodes when there is room', () => {
    expect(place([at(0, 100, 100), at(1, 400, 100)])).toEqual({ 0: 'bottom', 1: 'bottom' })
  })

  it('gives the spot below to the node with more trials and moves the other label up', () => {
    // Side by side, 40 px apart: 60 px wide labels below them would overlap.
    const small = at(0, 100, 100, { priority: 3 })
    const large = at(1, 140, 100, { priority: 9 })
    expect(place([small, large])).toEqual({ 0: 'top', 1: 'bottom' })
  })

  it('breaks a priority tie by data order', () => {
    expect(place([at(0, 100, 100, { priority: 5 }), at(1, 140, 100, { priority: 5 })])).toEqual({ 0: 'bottom', 1: 'top' })
  })

  it('places the anchor first, whatever its size', () => {
    const anchor = at(0, 100, 100, { priority: 1, anchor: true })
    const large = at(1, 140, 100, { priority: 9 })
    expect(place([anchor, large])).toEqual({ 0: 'bottom', 1: 'top' })
  })

  it('moves a label off another node', () => {
    // Node 1 sits right under node 0, where node 0's label would go.
    const above = at(0, 100, 100, { priority: 9 })
    const below = at(1, 100, 125, { priority: 1, radius: 6 })
    expect(place([above, below])).toEqual({ 0: 'top', 1: 'bottom' })
  })

  it('does not let a node block its own label', () => {
    expect(place([at(0, 100, 100, { radius: 30 })])).toEqual({ 0: 'bottom' })
  })

  it('uses the top when the bottom is cut off at the edge of the view', () => {
    expect(place([at(0, 400, 590)])).toEqual({ 0: 'top' })
  })

  it('tries the right, then the left, when above and below are cut off', () => {
    expect(place([at(0, 400, 20)], THIN)).toEqual({ 0: 'right' })
    expect(place([at(0, 780, 20)], THIN)).toEqual({ 0: 'left' })
  })

  it('lets a hub label cover a small unlabelled node when no side is clear', () => {
    // Small nodes sit in each of the hub's four label spots; the hub still gets a label.
    const hub = at(0, 100, 100, { priority: 9 })
    const below = at(1, 100, 121, { radius: 3 })
    const above = at(2, 100, 79, { radius: 3 })
    const right = at(3, 144, 100, { radius: 3 })
    const left = at(4, 56, 100, { radius: 3 })
    const sides = place([hub, below, above, right, left])
    expect(sides[0]).toBe('bottom')
    // The covered node stays unlabelled: it is drawn under the hub's label.
    expect(sides[1]).toBeUndefined()
  })

  it('never covers a labelled node, even when no side is clear', () => {
    // Node 1's spots are taken by node 0's label, node 0 itself, and the edge of the view.
    const labelled = at(0, 100, 100, { priority: 9 })
    const blocked = at(1, 130, 100, { radius: 5, priority: 1 })
    expect(place([labelled, blocked], { width: 180, height: 600 })).toEqual({ 0: 'bottom' })
  })

  it('hides a label that fits on no side', () => {
    expect(place([at(0, 400, 20, { width: 2000 })], THIN)).toEqual({})
  })
})
