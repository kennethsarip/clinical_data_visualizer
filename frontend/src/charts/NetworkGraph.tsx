import { useEffect, useImperativeHandle, useLayoutEffect, useRef } from 'react'
import cytoscape, { type Core, type EdgeSingular, type NodeSingular, type StylesheetJson } from 'cytoscape'
import { highlightedIndexes } from './highlight'
import { type LabelCandidate, type Side, placeLabels, sideBoxes } from './labelPlacement'
import { entityColor, legendGroups, toCytoscapeElements } from './networkElements'
import type { RendererProps } from './rendererProps'
import { THEME } from './theme'
import type { NetworkVisualization } from './types'

// Labels keep one on-screen size at every zoom (CLAUDE.md §14 Phase 8.2): fit-to-view shrank a
// spread-out graph's labels to ~7 px and blew a compact one's up to 18 px.
const LABEL = { fontPx: 12, gapPx: 4, outlinePx: 2, maxWidthPx: 120 }

export function NetworkGraph({ visualization, highlighted, onSelect, ref }: RendererProps<NetworkVisualization>) {
  const container = useRef<HTMLDivElement>(null)
  const cy = useRef<Core | null>(null)
  const select = useRef(onSelect)
  const highlight = useRef(highlighted)
  useLayoutEffect(() => {
    select.current = onSelect
    highlight.current = highlighted
  })

  useImperativeHandle(ref, () => ({
    ready: () => cy.current !== null,
    toSVG: null,
    toPNG: async () => {
      if (!cy.current) throw new Error('The network has not rendered yet')
      return cy.current.png({ output: 'base64uri', full: true, scale: 2, bg: '#ffffff' })
    },
  }), [])

  useEffect(() => {
    if (!container.current) return
    const { nodes, edges } = toCytoscapeElements(visualization)
    const graph = cytoscape({
      container: container.current,
      elements: [...nodes, ...edges],
      style: stylesheet(nodes.map((n) => n.data.size), edges.map((e) => e.data.weight)),
      layout: { name: 'concentric', animate: false },
      wheelSensitivity: 0.2,
      minZoom: 0.2,
      maxZoom: 3,
    })
    // Concentric seeds positions deterministically; force-directed cose then untangles them
    // without randomizing, so the same response draws the same graph.
    graph
      .layout({
        name: 'cose',
        animate: false,
        randomize: false,
        padding: 32,
        nodeRepulsion: () => 16000,
        idealEdgeLength: () => 80,
        nodeOverlap: 24,
        gravity: 1,
        numIter: 2500,
      })
      .run()
    const host = container.current
    relabel(graph, host)
    // Zoom and pan fire many viewport events per frame; place labels once per frame.
    let frame = 0
    graph.on('viewport resize', () => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => relabel(graph, host))
    })
    // Hover focuses a node's neighbourhood: everything else fades and its neighbours show labels.
    graph.on('mouseover', 'node', (event) => {
      const node: NodeSingular = event.target
      const near = node.closedNeighborhood()
      graph.batch(() => {
        node.addClass('hovered')
        near.nodes().not(node).addClass('neighbour')
        graph.elements().not(near).addClass('faded')
      })
    })
    graph.on('mouseout', 'node', () => {
      graph.batch(() => void graph.elements().removeClass('hovered neighbour faded'))
    })
    graph.on('tap', 'node', (event) => select.current({ kind: 'node', index: event.target.data('index') }))
    graph.on('tap', 'edge', (event) => select.current({ kind: 'edge', index: event.target.data('index') }))
    graph.on('tap', (event) => {
      if (event.target === graph) select.current(null)
    })
    cy.current = graph
    applyHighlight(graph, visualization, highlight.current)
    return () => {
      cancelAnimationFrame(frame)
      cy.current = null
      graph.destroy()
    }
  }, [visualization])

  useEffect(() => {
    if (cy.current) applyHighlight(cy.current, visualization, highlighted)
  }, [visualization, highlighted])

  const groups = legendGroups(toCytoscapeElements(visualization).nodes.map((n) => n.data))
  const hasAnchor = visualization.data.nodes.some((node) => node.is_anchor)
  return (
    <div className="network">
      <div ref={container} className="network-graph" />
      <ul className="network-legend" aria-label="Legend">
        {groups.map((group) => (
          <li key={group}>
            <span className="legend-mark" style={{ background: entityColor(group) }} />
            {group.charAt(0).toUpperCase() + group.slice(1)}
          </li>
        ))}
        {hasAnchor && (
          <li>
            <span className="legend-mark legend-anchor" />
            Faded: the entity you asked about (in every trial)
          </li>
        )}
        <li>
          <span className="legend-line" />
          Line thickness = shared trials
        </li>
      </ul>
    </div>
  )
}

function applyHighlight(graph: Core, viz: NetworkVisualization, highlighted: ReadonlySet<string>) {
  const nodes = new Set(highlightedIndexes(viz.data.nodes, highlighted))
  const edges = new Set(highlightedIndexes(viz.data.edges, highlighted))
  const active = highlighted.size > 0
  graph.batch(() => {
    graph.nodes().forEach((n) => void n.toggleClass('dim', active && !nodes.has(n.data('index'))))
    graph.edges().forEach((e) => void e.toggleClass('dim', active && !edges.has(e.data('index'))))
  })
}

/** Keeps label text at LABEL.fontPx on screen, then shows only the labels that fit, each on its
 *  chosen side (labelPlacement). Every node carries its label, drawn transparent unless placed, so
 *  the renderer reports each label's real box and placement never predicts text metrics. */
function relabel(graph: Core, host: HTMLElement) {
  const zoom = graph.zoom()
  graph.nodes().style({
    'font-size': LABEL.fontPx / zoom,
    'text-outline-width': LABEL.outlinePx / zoom,
    'text-max-width': `${LABEL.maxWidthPx / zoom}px`,
    ...sideStyle('bottom', zoom), // measured below; placement mirrors it to the other sides
  })
  const candidates: LabelCandidate[] = graph.nodes().map((node) => ({
    index: node.data('index') as number,
    body: node.renderedBoundingBox({ includeLabels: false }),
    labels: sideBoxes(node.renderedPosition(), node.renderedBoundingBox({ includeNodes: false, includeEdges: false, includeLabels: true })),
    priority: node.data('size') as number,
    anchor: node.hasClass('anchor'),
  }))
  const sides = placeLabels(candidates, { width: host.clientWidth, height: host.clientHeight })
  graph.batch(() => {
    graph.nodes().forEach((node) => {
      const side = sides.get(node.data('index') as number)
      node.toggleClass('labelled', side !== undefined)
      if (side) node.style(sideStyle(side, zoom))
    })
  })
}

/** Cytoscape's text alignment and margin for a label on one side, a constant gap on screen. */
function sideStyle(side: Side, zoom: number) {
  const gap = LABEL.gapPx / zoom
  const vertical = side === 'bottom' || side === 'top'
  return {
    'text-valign': vertical ? side : 'center',
    'text-halign': vertical ? 'center' : side,
    'text-margin-x': side === 'right' ? gap : side === 'left' ? -gap : 0,
    'text-margin-y': side === 'bottom' ? gap : side === 'top' ? -gap : 0,
  }
}

/** Sizes scale linearly between the smallest and largest value present, so a graph whose nodes
 *  all share one count still draws (Cytoscape's mapData needs min < max). */
function scaler(values: number[], low: number, high: number) {
  const min = Math.min(...values)
  const max = Math.max(...values)
  return (value: number) => (max === min ? (low + high) / 2 : low + ((value - min) / (max - min)) * (high - low))
}

function stylesheet(sizes: number[], weights: number[]): StylesheetJson {
  const nodeSize = scaler(sizes, 18, 56)
  const edgeWidth = scaler(weights, 1, 7)
  const edgeOpacity = scaler(weights, 0.35, 0.9)
  return [
    {
      selector: 'node',
      style: {
        'background-color': (n: NodeSingular) => entityColor(n.data('group') as string),
        width: (n: NodeSingular) => nodeSize(n.data('size') as number),
        height: (n: NodeSingular) => nodeSize(n.data('size') as number),
        // Every label is laid out (so its box is measurable) but drawn only once placed.
        label: 'data(label)',
        'text-opacity': 0,
        'text-outline-opacity': 0,
        color: THEME.textStrong,
        'font-family': THEME.font,
        'font-weight': 500,
        'text-wrap': 'ellipsis',
        'border-width': 2,
        'border-color': '#ffffff',
      },
    },
    {
      selector: 'node.labelled, node.hovered, node.neighbour, node:selected',
      style: {
        'text-opacity': 1,
        // A white halo keeps labels legible where they cross edges, without a boxy background.
        'text-outline-color': '#ffffff',
        'text-outline-opacity': 1,
      },
    },
    // Labelled nodes draw above the rest, so a label may cover an unlabelled node (labelPlacement).
    { selector: 'node.labelled', style: { 'z-index': 5 } },
    { selector: 'node.hovered, node:selected', style: { 'z-index': 10 } },
    { selector: 'node.anchor', style: { opacity: 0.35, 'font-style': 'italic' } },
    {
      selector: 'edge',
      style: {
        width: (e: EdgeSingular) => edgeWidth(e.data('weight') as number),
        // Heavier edges are also more opaque, so strong ties read first in a dense graph.
        opacity: (e: EdgeSingular) => edgeOpacity(e.data('weight') as number),
        'line-color': THEME.edge,
        'curve-style': 'unbundled-bezier',
        'control-point-distances': [12],
        'control-point-weights': [0.5],
      },
    },
    { selector: 'node.hovered, node.neighbour', style: { opacity: 1 } },
    { selector: '.dim, .faded', style: { opacity: 0.08 } },
    { selector: 'node:selected', style: { 'border-color': THEME.bubbleActive, 'border-width': 3 } },
    { selector: 'edge:selected', style: { 'line-color': THEME.bubbleActive } },
  ]
}
