import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { LoadingView } from './LoadingView'

beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

describe('LoadingView', () => {
  it('counts elapsed seconds from the start time', () => {
    const start = Date.now()
    render(<LoadingView startedAt={start} onCancel={() => {}} />)
    expect(screen.getByRole('status')).toHaveTextContent('0 s')
    act(() => vi.advanceTimersByTime(3000))
    expect(screen.getByRole('status')).toHaveTextContent('3 s')
  })

  it('cancels', () => {
    const onCancel = vi.fn()
    render(<LoadingView startedAt={Date.now()} onCancel={onCancel} />)
    act(() => screen.getByRole('button', { name: 'Cancel' }).click())
    expect(onCancel).toHaveBeenCalledOnce()
  })
})
