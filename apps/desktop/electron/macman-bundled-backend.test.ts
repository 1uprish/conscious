import assert from 'node:assert/strict'
import path from 'node:path'

import { test } from 'vitest'

import { resolveMacManBackendSource } from './macman-bundled-backend'

test('packaged MacMan prefers the backend source shipped inside its own bundle', () => {
  const resourcesPath = path.join(path.sep, 'Applications', 'MacMan.app', 'Contents', 'Resources')
  const bundledRoot = path.join(resourcesPath, 'macman-backend')

  assert.equal(
    resolveMacManBackendSource({
      resourcesPath,
      isPackaged: true,
      isSourceRoot: candidate => candidate === bundledRoot
    }),
    bundledRoot
  )
})

test('development and incomplete packages do not pretend a bundled backend exists', () => {
  const resourcesPath = path.join(path.sep, 'tmp', 'MacMan.app', 'Contents', 'Resources')

  assert.equal(
    resolveMacManBackendSource({ resourcesPath, isPackaged: false, isSourceRoot: () => true }),
    null
  )
  assert.equal(
    resolveMacManBackendSource({ resourcesPath, isPackaged: true, isSourceRoot: () => false }),
    null
  )
})
