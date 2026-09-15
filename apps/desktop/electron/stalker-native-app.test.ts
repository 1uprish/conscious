import assert from 'node:assert/strict'

import { test } from 'vitest'

import {
  buildStalkerLaunchRequests,
  buildStalkerOpenRequest,
  resolveStalkerApp,
  type StalkerNativePathIo
} from './stalker-native-app'

function pathIo(existing: string[]): StalkerNativePathIo {
  return {
    isDirectory: candidate => existing.includes(candidate),
    isExecutable: candidate => existing.includes(candidate)
  }
}

test('packaged Stalker resolves only the embedded MacMan companion', () => {
  const appPath = '/MacMan.app/Contents/Resources/stalker/MacMan Stalker.app'
  const executablePath = `${appPath}/Contents/MacOS/MacMan`

  assert.deepEqual(
    resolveStalkerApp({
      allowDevelopmentFallback: false,
      appRoot: '/source/apps/desktop',
      architecture: 'arm64',
      io: pathIo([appPath, executablePath]),
      resourcesPath: '/MacMan.app/Contents/Resources'
    }),
    { appPath, executablePath }
  )
  assert.equal(
    resolveStalkerApp({
      allowDevelopmentFallback: false,
      appRoot: '/source/apps/desktop',
      architecture: 'arm64',
      io: pathIo(['/source/apps/desktop/build/macman-stalker/MacMan Stalker.app']),
      resourcesPath: '/MacMan.app/Contents/Resources'
    }),
    null
  )
})

test('Stalker views use the embedded app and MacMan-owned deeplinks', () => {
  const appPath = '/MacMan.app/Contents/Resources/stalker/MacMan Stalker.app'

  assert.deepEqual(buildStalkerOpenRequest(appPath, 'timeline'), {
    args: ['-a', appPath, 'macman-stalker://timeline'],
    command: '/usr/bin/open'
  })
  assert.deepEqual(buildStalkerOpenRequest(appPath, 'search'), {
    args: ['-a', appPath, 'macman-stalker://search'],
    command: '/usr/bin/open'
  })
  assert.deepEqual(buildStalkerLaunchRequests(appPath, 'timeline'), [
    {
      args: ['-f', appPath],
      command: '/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister'
    },
    {
      args: ['-a', appPath, 'macman-stalker://timeline'],
      command: '/usr/bin/open'
    }
  ])
})
