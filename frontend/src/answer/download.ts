// Saves exports (response JSON, chart SVG/PNG) as files named after the chart title.

/** `Trials by Phase for Pembrolizumab`, `svg` -> `trials-by-phase-for-pembrolizumab.svg`. */
export function fileName(title: string, extension: string): string {
  const slug = title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 80)
    .replace(/-+$/, '')
  return `${slug || 'chart'}.${extension}`
}

export function downloadText(name: string, text: string, type: string): void {
  const href = URL.createObjectURL(new Blob([text], { type }))
  downloadUrl(name, href)
  URL.revokeObjectURL(href)
}

export function downloadUrl(name: string, href: string): void {
  const link = document.createElement('a')
  link.href = href
  link.download = name
  link.click()
}
