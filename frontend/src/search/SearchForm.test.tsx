import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { SearchForm } from './SearchForm'

function setup(busy = false) {
  const onSubmit = vi.fn()
  const user = userEvent.setup()
  render(<SearchForm busy={busy} onSubmit={onSubmit} />)
  const query = screen.getByRole('textbox', { name: /ask about clinical trials/i })
  return { onSubmit, user, query }
}

describe('SearchForm', () => {
  it('submits the trimmed question', async () => {
    const { onSubmit, user, query } = setup()
    await user.type(query, '  phases of melanoma trials ')
    await user.click(screen.getByRole('button', { name: 'Visualize' }))
    expect(onSubmit).toHaveBeenCalledExactlyOnceWith({ query: 'phases of melanoma trials' })
  })

  it('submits on Enter and adds a line on Shift+Enter', async () => {
    const { onSubmit, user, query } = setup()
    await user.type(query, 'melanoma{Shift>}{Enter}{/Shift}phases')
    expect(onSubmit).not.toHaveBeenCalled()
    expect(query).toHaveValue('melanoma\nphases')
    await user.type(query, '{Enter}')
    expect(onSubmit).toHaveBeenCalledExactlyOnceWith({ query: 'melanoma\nphases' })
  })

  it('shows an error instead of submitting a blank question', async () => {
    const { onSubmit, user } = setup()
    await user.click(screen.getByRole('button', { name: 'Visualize' }))
    expect(onSubmit).not.toHaveBeenCalled()
    expect(screen.getByText('Enter a question.')).toBeInTheDocument()
  })

  it('shows no example-question chips', () => {
    setup()
    expect(screen.queryByRole('group', { name: /example questions/i })).not.toBeInTheDocument()
  })

  it('has no filter fields: filtering comes from the question alone', () => {
    setup()
    expect(screen.queryByRole('button', { name: /filters/i })).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Condition')).not.toBeInTheDocument()
  })

  it('disables submitting while a request is running', () => {
    setup(true)
    expect(screen.getByRole('button', { name: 'Visualize' })).toBeDisabled()
  })
})
