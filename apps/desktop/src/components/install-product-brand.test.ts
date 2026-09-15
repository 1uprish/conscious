import { describe, expect, it } from 'vitest'

import { rebrandInstallCopy } from './install-product-brand'

describe('rebrandInstallCopy', () => {
  it('keeps the canonical installer copy unchanged for Hermes', () => {
    const copy = { title: 'Set up Hermes Desktop' }

    expect(rebrandInstallCopy(copy, 'Hermes')).toBe(copy)
  })

  it('rebrands nested strings and function results without changing installer behavior', () => {
    const copy = {
      description: 'Install Hermes Agent or connect to a Hermes gateway.',
      nested: { title: 'Set up Hermes Desktop' },
      status: (count: number) => `${count} Hermes steps`
    }

    const branded = rebrandInstallCopy(copy, 'MacMan')

    expect(branded.description).toBe('Install MacMan or connect to a MacMan gateway.')
    expect(branded.nested.title).toBe('Set up MacMan')
    expect(branded.status(2)).toBe('2 MacMan steps')
  })
})
