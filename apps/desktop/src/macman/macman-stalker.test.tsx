import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'

import { MacManStalker } from './macman-stalker'

afterEach(() => vi.restoreAllMocks())

test('shows the native Stalker state and enables it from one explicit action', async () => {
  const snapshot = vi.fn(async () => ({
    archiveBytes: 0,
    desiredEnabled: false,
    manuallyPaused: false,
    runtimeState: 'off' as const
  }))
  const enable = vi.fn(async () => ({
    archiveBytes: 0,
    desiredEnabled: true,
    manuallyPaused: false,
    runtimeState: 'running' as const
  }))
  Object.assign(window.hermesDesktop, {
    stalker: { disable: vi.fn(), enable, open: vi.fn(), retry: vi.fn(), snapshot }
  })

  render(<MacManStalker />)
  expect(await screen.findByText('Off')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Turn on Stalker' }))
  await waitFor(() => expect(enable).toHaveBeenCalledOnce())
  expect(await screen.findByText('Running')).toBeInTheDocument()
})

test('reports an unavailable bridge truthfully', async () => {
  const previous = window.hermesDesktop.stalker
  delete window.hermesDesktop.stalker
  render(<MacManStalker />)
  expect(await screen.findByText('Unavailable')).toBeInTheDocument()
  window.hermesDesktop.stalker = previous
})
