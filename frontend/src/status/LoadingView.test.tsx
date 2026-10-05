import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { LoadingView } from './LoadingView'

beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

describe('LoadingView', () => {
  it('counts elapsed seconds from the start time', () => {
    const start = Date.now()
    render(<LoadingView startedAt={start} query="melanoma phases" onCancel={() => {}} />)
    expect(screen.getByRole('status')).toHaveTextContent('0 s')
    act(() => vi.advanceTimersByTime(3000))
    expect(screen.getByRole('status')).toHaveTextContent('3 s')
  })

  it('echoes the question being answered', () => {
    render(<LoadingView startedAt={Date.now()} query="melanoma phases" onCancel={() => {}} />)
    expect(screen.getByText('“melanoma phases”')).toBeInTheDocument()
  })

  it('cancels', () => {
    const onCancel = vi.fn()
    render(<LoadingView startedAt={Date.now()} query="melanoma phases" onCancel={onCancel} />)
    act(() => screen.getByRole('button', { name: 'Cancel' }).click())
    expect(onCancel).toHaveBeenCalledOnce()
  })
})
