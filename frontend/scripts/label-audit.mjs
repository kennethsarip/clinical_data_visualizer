// Network label audit (CLAUDE.md §14 Phase 8.2). Drives an already-running headless Chrome over the
// DevTools protocol (no extra dependency): asks each question in the running frontend, waits for the
// network, then measures every visible label's rendered box. Needs the backend and frontend running;
// not part of CI. Prints, per network: zoom at fit, label font size on screen, how many of the 10
// largest nodes are labelled, labels shown, label pairs that overlap, labels over a labelled node
// (must be 0) and over an unlabelled one (allowed: drawn beneath), labels cut off at the edge.
// Screenshots go to <outDir>.
//
//   "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new \
//     --remote-debugging-port=9222 --user-data-dir=/tmp/label-audit about:blank &
//   node scripts/label-audit.mjs /tmp/shots melanoma "Which drugs frequently co-occur ... melanoma?"
//
// APP_URL (default http://localhost:5173) and CDP_PORT (default 9222) override the defaults.
import { mkdirSync, writeFileSync } from 'node:fs'
const [, , outDir, ...pairs] = process.argv
mkdirSync(outDir, { recursive: true })
const APP_URL = process.env.APP_URL ?? 'http://localhost:5173'
const CDP_PORT = process.env.CDP_PORT ?? '9222'
const version = await (await fetch(`http://localhost:${CDP_PORT}/json/new?about:blank`, { method: 'PUT' })).json()
const ws = new WebSocket(version.webSocketDebuggerUrl)
await new Promise((r) => ws.addEventListener('open', r))
let id = 0
const pending = new Map()
ws.addEventListener('message', (m) => { const d = JSON.parse(m.data); if (pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id) } })
const send = (method, params = {}) => new Promise((r) => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })) })
const evaluate = async (expression) => (await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true })).result
await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1100, deviceScaleFactor: 1, mobile: false })
const MEASURE = `(() => {
  const el = document.querySelector('.network-graph'); const cy = el._cyreg.cy
  const zoom = cy.zoom()
  const shown = cy.nodes().filter((n) => n.style('label') && Number(n.style('text-opacity')) > 0)
  const box = (b) => ({ x1: b.x1, y1: b.y1, x2: b.x2, y2: b.y2 })
  const labels = shown.map((n) => ({ id: n.id(), label: n.style('label'), b: box(n.renderedBoundingBox({ includeNodes: false, includeEdges: false, includeLabels: true })) }))
  const bodies = cy.nodes().map((n) => ({ id: n.id(), b: box(n.renderedBoundingBox({ includeNodes: true, includeEdges: false, includeLabels: false })) }))
  const hit = (a, b) => a.x1 < b.x2 && b.x1 < a.x2 && a.y1 < b.y2 && b.y1 < a.y2
  const overlaps = []
  for (let i = 0; i < labels.length; i++) for (let j = i + 1; j < labels.length; j++) if (hit(labels[i].b, labels[j].b)) overlaps.push([labels[i].label, labels[j].label])
  // A label may cover an unlabelled node (drawn beneath it) but never a labelled one.
  const labelledIds = new Set(labels.map((l) => l.id))
  const overLabelled = [], overUnlabelled = []
  for (const l of labels) for (const n of bodies) if (n.id !== l.id && hit(l.b, n.b)) (labelledIds.has(n.id) ? overLabelled : overUnlabelled).push([l.label, n.id])
  const w = el.clientWidth, h = el.clientHeight
  const clipped = labels.filter((l) => l.b.x1 < 0 || l.b.y1 < 0 || l.b.x2 > w || l.b.y2 > h).map((l) => l.label)
  const fontPx = labels.length ? parseFloat(cy.getElementById(labels[0].id).renderedStyle('font-size')) : null; const shownIds = new Set(labels.map((l) => l.id)); const top10 = cy.nodes().sort((a, b) => b.data('size') - a.data('size')).slice(0, 10); const top10Labelled = top10.filter((n) => shownIds.has(n.id())).length; return { zoom, fontPx, top10Labelled, nodes: cy.nodes().length, labelsShown: labels.length, labelOverlaps: overlaps.length, labelOverLabelledNode: overLabelled.length, labelOverUnlabelledNode: overUnlabelled.length, clipped: clipped.length, examples: overlaps.slice(0, 4) }
})()`
const results = {}
for (let i = 0; i < pairs.length; i += 2) {
  const [name, query] = [pairs[i], pairs[i + 1]]
  await send('Page.navigate', { url: APP_URL })
  await new Promise((r) => setTimeout(r, 1500))
  await evaluate(`(() => { const t = document.querySelector('textarea'); const set = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set; set.call(t, ${JSON.stringify(query)}); t.dispatchEvent(new Event('input', { bubbles: true })); document.querySelector('button[type=submit]').click() })()`)
  await evaluate(`new Promise((r) => { const tick = () => { const el = document.querySelector('.network-graph'); if (el && el._cyreg && el._cyreg.cy) setTimeout(r, 800); else setTimeout(tick, 200) }; tick() })`)
  const res = await evaluate(MEASURE); results[name] = res.result.value
  await evaluate(`document.querySelector('.network-graph').scrollIntoView({ block: 'center' })`)
  const shot = await send('Page.captureScreenshot', { format: 'png' })
  writeFileSync(`${outDir}/${name}.png`, Buffer.from(shot.result.data, 'base64'))
}
console.log(JSON.stringify(results, null, 1))
process.exit(0)
