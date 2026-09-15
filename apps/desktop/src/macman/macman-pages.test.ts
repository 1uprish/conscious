import { describe, expect, it } from 'vitest'

import { deriveSetupSnapshot } from './macman-pages'

describe('deriveSetupSnapshot', () => {
  it('reports each authoritative capability as ready when its live signal is ready', () => {
    expect(
      deriveSetupSnapshot({
        computer: { platform_supported: true, ready: true },
        memory: { active: true },
        messaging: [
          { enabled: true, state: 'disconnected' },
          { enabled: true, state: 'connected' }
        ],
        model: { model: 'deepseek-chat', provider: 'deepseek' }
      })
    ).toEqual({
      computer: 'ready',
      memory: 'ready',
      messaging: 'ready',
      model: 'ready'
    })
  })

  it('does not treat saved or disabled messaging configuration as a live connection', () => {
    expect(
      deriveSetupSnapshot({
        computer: { platform_supported: true, ready: false },
        memory: { active: false },
        messaging: [
          { enabled: false, state: 'connected' },
          { enabled: true, state: 'configured' }
        ],
        model: { model: null, provider: 'deepseek' }
      })
    ).toEqual({
      computer: 'needs-setup',
      memory: 'needs-setup',
      messaging: 'optional',
      model: 'needs-setup'
    })
  })

  it('maps failed authority requests to recoverable unavailable or setup states', () => {
    expect(deriveSetupSnapshot({})).toEqual({
      computer: 'unavailable',
      memory: 'needs-setup',
      messaging: 'optional',
      model: 'needs-setup'
    })
  })
})
