// Chart colours. Vega and Cytoscape take literal colours, not CSS variables, so these mirror the
// tokens in src/index.css (sampled from the reference product); change both together.
export const THEME = {
  font: "'Pretendard Variable', Pretendard, system-ui, sans-serif",
  text: '#4a5057',
  textStrong: '#1a1a1a',
  muted: '#8f8f8f',
  blueBorder: '#cddaea',
  grid: '#eef1f5',
  accent: '#4a8fd8',
  bubbleActive: '#5b84aa',
  // Series and entity colours: accent blue first, then the reference's teal, then distinct hues.
  series: ['#4a8fd8', '#2aa7b0', '#8b7fd6', '#e0a03a', '#d36b8f', '#7a8ba3'],
} as const
