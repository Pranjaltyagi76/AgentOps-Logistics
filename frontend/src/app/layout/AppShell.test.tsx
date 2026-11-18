import { fireEvent, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { renderRoutes, signIn } from '@/test/render'

import { AppShell } from './AppShell'

function renderShell() {
  return renderRoutes(
    [
      {
        path: '/',
        element: <AppShell />,
        children: [
          { path: 'dashboard', element: <p>dashboard page</p> },
          { path: 'runs', element: <p>runs page</p> },
        ],
      },
    ],
    '/dashboard',
  )
}

describe('app shell', () => {
  afterEach(() => signIn(null))

  it('opens the mobile menu, closes it on Escape and after navigating', () => {
    signIn('viewer')
    renderShell()
    expect(screen.getByText('dashboard page')).toBeInTheDocument()
    expect(screen.queryByRole('dialog', { name: 'Menu' })).not.toBeInTheDocument()

    const toggle = screen.getByRole('button', { name: 'Open menu' })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    fireEvent.click(toggle)
    const menu = screen.getByRole('dialog', { name: 'Menu' })
    expect(within(menu).getByRole('link', { name: 'Runs' })).toBeInTheDocument()
    expect(within(menu).getByText('Demo viewer')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Close menu' }).length).toBeGreaterThan(0)

    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('dialog', { name: 'Menu' })).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Open menu' }))
    fireEvent.click(within(screen.getByRole('dialog', { name: 'Menu' })).getByRole('link', { name: 'Runs' }))
    expect(screen.getByText('runs page')).toBeInTheDocument()
    expect(screen.queryByRole('dialog', { name: 'Menu' })).not.toBeInTheDocument()
  })
})
