import { describe, expect, it } from 'vitest'

import { DEFERRED_MACMAN_CAPABILITIES, MACMAN_NAVIGATION, MACMAN_VIEWS, macManNavigationItem } from './navigation'

describe('MacMan navigation contract', () => {
  it('contains every approved primary and settings destination exactly once', () => {
    expect(MACMAN_NAVIGATION.map(group => group.id)).toEqual(['primary', 'settings'])
    expect(MACMAN_VIEWS).toEqual([
      'chat',
      'setup',
      'permissions',
      'general',
      'models',
      'messaging',
      'voice',
      'notifications',
      'browser',
      'memory',
      'privacy',
      'workspace',
      'capabilities',
      'advanced',
      'about'
    ])
    expect(new Set(MACMAN_VIEWS).size).toBe(MACMAN_VIEWS.length)
  })

  it('keeps deferred Apple-data integrations visible without claiming they work', () => {
    expect(DEFERRED_MACMAN_CAPABILITIES.map(item => item.id)).toEqual(['contacts', 'calendar', 'reminders'])
  })

  it('resolves the user-facing title and purpose for every destination', () => {
    for (const view of MACMAN_VIEWS) {
      const item = macManNavigationItem(view)

      expect(item.id).toBe(view)
      expect(item.label.trim()).not.toBe('')
      expect(item.description.trim()).not.toBe('')
    }
  })
})
