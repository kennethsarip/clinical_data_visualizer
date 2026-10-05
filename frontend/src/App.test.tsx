import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import App from './App'

describe('App shell', () => {
  it('renders the product name and the query box', () => {
    render(<App />)
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Trials Explorer')
    expect(screen.getByRole('textbox', { name: /ask about clinical trials/i })).toBeInTheDocument()
  })
})
