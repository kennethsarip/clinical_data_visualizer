// Chart colours. Vega and Cytoscape take literal colours, not CSS variables, so these mirror the
// tokens in src/index.css (taken from the PhnyX Lab site); change both together.
export const THEME = {
  font: "Inter, 'Pretendard Variable', Pretendard, system-ui, sans-serif",
  text: '#444444',
  textStrong: '#121212',
  muted: '#808080',
  blueBorder: '#c7dfff',
  edge: '#8fb4e6', // network edges: the accent, lightened so nodes stay on top
  grid: '#eceff2',
  accent: '#287deb',
  bubbleActive: '#1e59af',
  // Series and entity colours: accent blue first, then the reference's teal, then distinct hues.
  series: ['#287deb', '#2aa7b0', '#8b7fd6', '#e0a03a', '#d36b8f', '#7a8ba3'],
} as const
