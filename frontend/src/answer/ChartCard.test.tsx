import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useImperativeHandle } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { components } from '../api/types'
import type { RendererProps } from '../charts/rendererProps'
import type { Visualization } from '../charts/types'
import { VISUALIZATION_EXAMPLES, exampleWith } from '../test/schemasExamples'
import { ChartCard } from './ChartCard'

type OkResponse = components['schemas']['OkResponse']

// A stand-in renderer exposing the export handle the real ones provide; Cytoscape has no SVG.
vi.mock('../charts/ChartView', () => ({
  ChartView: ({ visualization, ref }: RendererProps<Visualization>) => {
    const network = visualization.type === 'network_graph'
    useImperativeHandle(ref, () => ({
      ready: () => true,
      toSVG: network ? null : async () => '<svg>chart</svg>',
      toPNG: async () => 'data:image/png;base64,AAAA',
    }), [network])
    return <p>drawn chart</p>
  },
}))

const BAR = exampleWith((r) => r.status === 'ok' && r.visualization?.type === 'bar_chart') as OkResponse
const NETWORK = {
  ...BAR,
  visualization: VISUALIZATION_EXAMPLES.find((v) => v.type === 'network_graph'),
} as OkResponse

let downloads: { name: string; href: string }[]
let blobs: Blob[]
beforeEach(() => {
  downloads = []
  blobs = []
  vi.stubGlobal('URL', Object.assign(URL, {
    createObjectURL: (blob: Blob) => {
      blobs.push(blob)
      return `blob:${blobs.length}`
    },
    revokeObjectURL: () => {},
  }))
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
    downloads.push({ name: this.download, href: this.getAttribute('href') ?? '' })
  })
})
afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

function renderCard(response: OkResponse) {
  render(<ChartCard response={response} highlighted={new Set()} onSelect={() => {}} />)
}

describe('ChartCard response JSON', () => {
  it('starts on the chart and switches to the exact response', async () => {
    const user = userEvent.setup()
    renderCard(BAR)
    expect(await screen.findByText('drawn chart')).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Chart' })).toHaveAttribute('aria-selected', 'true')

    await user.click(screen.getByRole('tab', { name: 'Response JSON' }))
    expect(screen.queryByText('drawn chart')).not.toBeInTheDocument()
    expect(screen.getByLabelText('Response JSON').textContent).toBe(JSON.stringify(BAR, null, 2))

    await user.click(screen.getByRole('tab', { name: 'Chart' }))
    expect(await screen.findByText('drawn chart')).toBeInTheDocument()
  })

  it('copies the response to the clipboard', async () => {
    const user = userEvent.setup()
    const writeText = vi.spyOn(navigator.clipboard, 'writeText')
    renderCard(BAR)
    await user.click(screen.getByRole('tab', { name: 'Response JSON' }))
    await user.click(screen.getByRole('button', { name: 'Copy' }))
    expect(writeText).toHaveBeenCalledWith(JSON.stringify(BAR, null, 2))
    expect(screen.getByRole('button', { name: 'Copied' })).toBeInTheDocument()
  })

  it('downloads the response as a file named after the title', async () => {
    const user = userEvent.setup()
    renderCard(BAR)
    await user.click(screen.getByRole('tab', { name: 'Response JSON' }))
    await user.click(screen.getByRole('button', { name: 'Download JSON' }))
    expect(downloads).toEqual([{ name: 'trials-by-phase-for-pembrolizumab.json', href: 'blob:1' }])
    expect(blobs[0].type).toBe('application/json')
    expect(await blobs[0].text()).toBe(JSON.stringify(BAR, null, 2))
  })
})

describe('ChartCard chart export', () => {
  it('downloads the chart as SVG and PNG', async () => {
    const user = userEvent.setup()
    renderCard(BAR)
    await screen.findByText('drawn chart')
    await user.click(screen.getByRole('button', { name: 'Download SVG' }))
    await user.click(screen.getByRole('button', { name: 'Download PNG' }))
    expect(downloads).toEqual([
      { name: 'trials-by-phase-for-pembrolizumab.svg', href: 'blob:1' },
      { name: 'trials-by-phase-for-pembrolizumab.png', href: 'data:image/png;base64,AAAA' },
    ])
    expect(blobs[0].type).toBe('image/svg+xml')
    expect(await blobs[0].text()).toBe('<svg>chart</svg>')
  })

  it('offers only PNG for a network, which draws to canvas', async () => {
    renderCard(NETWORK)
    await screen.findByText('drawn chart')
    expect(screen.queryByRole('button', { name: 'Download SVG' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Download PNG' })).toBeInTheDocument()
  })

  it('hides chart export while the JSON is shown', async () => {
    const user = userEvent.setup()
    renderCard(BAR)
    await screen.findByText('drawn chart')
    await user.click(screen.getByRole('tab', { name: 'Response JSON' }))
    expect(screen.queryByRole('button', { name: 'Download PNG' })).not.toBeInTheDocument()
  })
})

describe('ChartCard capped sample', () => {
  it('says under the title when the counts come from a capped sample', async () => {
    const capped = { ...BAR, meta: { ...BAR.meta, sample: [{ cohort: null, fetched: 10000, total: 123756, capped: true }] } } as OkResponse
    renderCard(capped)
    expect(screen.getByRole('note')).toHaveTextContent('Counts come from 10,000 of 123,756 matching trials')
    expect(await screen.findByText('drawn chart')).toBeInTheDocument()
  })

  it('stays quiet when every matching trial was fetched', () => {
    renderCard(BAR)
    expect(screen.queryByRole('note')).not.toBeInTheDocument()
  })
})
