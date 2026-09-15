import { describe, expect, it } from 'vitest'

import { MACMAN_PRESENTATION, presentProductCopy } from './product-presentation'

describe('presentProductCopy', () => {
  it('rebrands visible product copy without altering ordinary words', () => {
    expect(presentProductCopy('Give Hermes a task', MACMAN_PRESENTATION)).toBe('Give MacMan a task')
    expect(presentProductCopy('Setting up Hermes Agent', MACMAN_PRESENTATION)).toBe('Setting up MacMan')
    expect(presentProductCopy('Ask anything', MACMAN_PRESENTATION)).toBe('Ask anything')
  })
})
