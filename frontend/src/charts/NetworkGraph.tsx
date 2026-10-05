import { useEffect, useImperativeHandle, useLayoutEffect, useRef } from 'react'
import cytoscape, { type Core, type EdgeSingular, type NodeSingular, type StylesheetJson } from 'cytoscape'
import { highlightedIndexes } from './highlight'
import { labelledNodes, toCytoscapeElements } from './networkElements'
import type { RendererProps } from './rendererProps'
import { THEME } from './theme'
import type { NetworkVisualization } from './types'

const PERMANENT_LABELS = 12

const ENTITY_COLORS: Record<string, string> = {
  drug: THEME.series[0],
  sponsor: THEME.series[1],
  condition: THEME.series[2],
}

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
    const anchor = visualization.data.nodes.findIndex((node) => node.is_anchor)
    const labelled = labelledNodes(nodes.map((n) => n.data), PERMANENT_LABELS, anchor >= 0 ? anchor : undefined)
    for (const node of nodes) if (labelled.has(node.data.index)) node.classes = `${node.classes} labelled`.trim()
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
    graph.on('mouseover', 'node', (event) => void event.target.addClass('hovered'))
    graph.on('mouseout', 'node', (event) => void event.target.removeClass('hovered'))
    graph.on('tap', 'node', (event) => select.current({ kind: 'node', index: event.target.data('index') }))
    graph.on('tap', 'edge', (event) => select.current({ kind: 'edge', index: event.target.data('index') }))
    graph.on('tap', (event) => {
      if (event.target === graph) select.current(null)
    })
    cy.current = graph
    applyHighlight(graph, visualization, highlight.current)
    return () => {
      cy.current = null
      graph.destroy()
    }
  }, [visualization])

  useEffect(() => {
    if (cy.current) applyHighlight(cy.current, visualization, highlighted)
  }, [visualization, highlighted])

  return <div ref={container} className="network-graph" />
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

/** Sizes scale linearly between the smallest and largest value present, so a graph whose nodes
 *  all share one count still draws (Cytoscape's mapData needs min < max). */
function scaler(values: number[], low: number, high: number) {
  const min = Math.min(...values)
  const max = Math.max(...values)
  return (value: number) => (max === min ? (low + high) / 2 : low + ((value - min) / (max - min)) * (high - low))
}

function stylesheet(sizes: number[], weights: number[]): StylesheetJson {
  const nodeSize = scaler(sizes, 18, 56)
  const edgeWidth = scaler(weights, 1.5, 8)
  return [
    {
      selector: 'node',
      style: {
        'background-color': (n: NodeSingular) => ENTITY_COLORS[n.data('group') as string] ?? THEME.accent,
        width: (n: NodeSingular) => nodeSize(n.data('size') as number),
        height: (n: NodeSingular) => nodeSize(n.data('size') as number),
        label: '',
        color: THEME.textStrong,
        'font-family': THEME.font,
        'font-size': 13,
        'text-valign': 'bottom',
        'text-margin-y': 4,
        'text-wrap': 'ellipsis',
        'text-max-width': '120px',
        'border-width': 2,
        'border-color': '#ffffff',
      },
    },
    {
      selector: 'node.labelled, node.hovered, node:selected',
      style: {
        label: 'data(label)',
        'text-background-color': '#ffffff',
        'text-background-opacity': 0.85,
        'text-background-padding': '2px',
        'text-background-shape': 'roundrectangle',
      },
    },
    { selector: 'node.hovered, node:selected', style: { 'z-index': 10 } },
    { selector: 'node.anchor', style: { opacity: 0.35, 'font-style': 'italic' } },
    {
      selector: 'edge',
      style: {
        width: (e: EdgeSingular) => edgeWidth(e.data('weight') as number),
        'line-color': THEME.blueBorder,
        'curve-style': 'haystack',
        opacity: 0.85,
      },
    },
    { selector: '.dim', style: { opacity: 0.12 } },
    { selector: 'node:selected', style: { 'border-color': THEME.bubbleActive, 'border-width': 3 } },
    { selector: 'edge:selected', style: { 'line-color': THEME.bubbleActive } },
  ]
}
