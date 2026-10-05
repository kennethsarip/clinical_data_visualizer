import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { EXAMPLES } from './examples'
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

  it('runs an example chip as-is, clearing filters', async () => {
    const { onSubmit, user, query } = setup()
    await user.click(screen.getByRole('button', { name: /filters/i }))
    await user.type(screen.getByLabelText('Drug'), 'aspirin')
    const network = EXAMPLES.find((e) => e.questionClass === 'network')!
    const chips = screen.getByRole('group', { name: /example questions/i })
    expect(within(chips).getAllByRole('button')).toHaveLength(6)
    await user.click(within(chips).getByRole('button', { name: new RegExp(network.label) }))
    expect(onSubmit).toHaveBeenCalledExactlyOnceWith({ query: network.query })
    expect(query).toHaveValue(network.query)
    expect(screen.getByLabelText('Drug')).toHaveValue('')
  })

  it('keeps filters collapsed until opened, then sends them and counts them', async () => {
    const { onSubmit, user, query } = setup()
    const toggle = screen.getByRole('button', { name: /filters/i })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByLabelText('Condition')).not.toBeInTheDocument()
    await user.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    await user.type(screen.getByLabelText('Condition'), 'Melanoma')
    await user.selectOptions(screen.getByLabelText('Phase'), 'Phase 3')
    expect(toggle).toHaveTextContent('2')
    await user.type(query, 'sponsor classes')
    await user.click(screen.getByRole('button', { name: 'Visualize' }))
    expect(onSubmit).toHaveBeenCalledExactlyOnceWith({
      query: 'sponsor classes',
      condition: 'Melanoma',
      trial_phase: 'PHASE3',
    })
  })

  it('shows a contradictory year range next to the end year', async () => {
    const { onSubmit, user, query } = setup()
    await user.click(screen.getByRole('button', { name: /filters/i }))
    await user.type(screen.getByLabelText('Start year'), '2022')
    await user.type(screen.getByLabelText('End year'), '2018')
    await user.type(query, 'melanoma per year{Enter}')
    expect(onSubmit).not.toHaveBeenCalled()
    expect(screen.getByLabelText('End year')).toHaveAccessibleDescription(
      'End year must not be before the start year.',
    )
  })

  it('disables submitting while a request is running', () => {
    setup(true)
    expect(screen.getByRole('button', { name: 'Visualize' })).toBeDisabled()
  })
})
