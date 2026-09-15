import assert from 'node:assert/strict'

import { test } from 'vitest'

import {
  isSupportedStalkerPack,
  MACMAN_STALKER_APP_NAME,
  MACMAN_STALKER_BUNDLE_ID,
  MACMAN_STALKER_SCHEME,
  UPSTREAM_SOURCE_COMMIT,
  UPSTREAM_SOURCE_SHA256,
  UPSTREAM_SOURCE_URL,
  rebrandStalkerSourceText,
  validateStagedStalkerApp
} from './stage-macman-stalker.mjs'

test('the Stalker packaging gate is exact, MacMan-only, and arm64-only', () => {
  assert.equal(isSupportedStalkerPack({ architecture: 'arm64', electronPlatformName: 'darwin', productFilename: 'MacMan' }), true)
  assert.equal(isSupportedStalkerPack({ architecture: 'x64', electronPlatformName: 'darwin', productFilename: 'MacMan' }), false)
  assert.equal(isSupportedStalkerPack({ architecture: 'arm64', electronPlatformName: 'darwin', productFilename: 'Hermes' }), false)
  assert.equal(isSupportedStalkerPack({ architecture: 'arm64', electronPlatformName: 'win32', productFilename: 'MacMan' }), false)
})

test('the source rebrand separates runtime identity, data, and native deeplinks from the upstream app', () => {
  const branded = rebrandStalkerSourceText('Shared/AppPaths.swift', 'Retrace io.retrace.app com.retrace.database ~/Library/Application Support/Retrace /Library/Logs/Retrace retrace://timeline')
  assert.equal(branded, 'MacMan com.macman.stalker com.macman.stalker.database ~/Library/Application Support/MacMan/Stalker /Library/Logs/MacMan/Stalker macman-stalker://timeline')
  assert.equal(rebrandStalkerSourceText('UI/Components/DeeplinkHandler.swift', 'components.scheme = "retrace"'), 'components.scheme = "macman-stalker"')
})

test('the Stalker dashboard registers its own TCC identities before opening Settings', () => {
  const source = `
                    action: {
                        SystemSettingsOpener.openAccessibilitySettings()
                    },
                    action: {
                        SystemSettingsOpener.openScreenRecordingSettings()
                    },
  `

  const branded = rebrandStalkerSourceText('UI/Views/Dashboard/DashboardView.swift', source)

  assert.match(branded, /kAXTrustedCheckOptionPrompt/)
  assert.match(branded, /AXIsProcessTrustedWithOptions/)
  assert.match(branded, /SystemSettingsOpener\.openAccessibilitySettings\(\)/)
  assert.ok(branded.indexOf('AXIsProcessTrustedWithOptions') < branded.indexOf('openAccessibilitySettings'))
  assert.match(branded, /import ScreenCaptureKit/)
  assert.match(branded, /try await SCShareableContent\.excludingDesktopWindows/)
  assert.match(branded, /SystemSettingsOpener\.openScreenRecordingSettings\(\)/)
  assert.ok(branded.indexOf('SCShareableContent') < branded.indexOf('openScreenRecordingSettings'))
})

test('the Stalker menu bar uses the MacMan app icon instead of the upstream triangles', () => {
  const source = `
        // Check for updates
        // Get Help

    @objc private func openFeedback() {
    }

    @objc private func checkForUpdatesFromMenu() {
    }

        button.image?.isTemplate = true

    /// Create a custom status icon with two triangles (Retrace logo)
    private func createStatusIcon(style: RecordingStatusIconStyle, scale: CGFloat = 1.0) -> NSImage {
        let leftTriangle = NSBezierPath()
        let rightTriangle = NSBezierPath()
        return NSImage()
    }

    /// Create a custom view with a toggle switch for recording
  `

  const branded = rebrandStalkerSourceText('UI/Components/MenuBarManager.swift', source)

  assert.match(branded, /NSApp\.applicationIconImage/)
  assert.match(branded, /button\.image\?\.isTemplate = false/)
  assert.doesNotMatch(branded, /leftTriangle|rightTriangle|Retrace logo/)
})

test('Stalker pins the audited native source and gives the companion a MacMan-owned identity', () => {
  assert.equal(UPSTREAM_SOURCE_COMMIT, 'd9313842f2e752b4f8ddaa572b4a22fdbbfac7c2')
  assert.equal(UPSTREAM_SOURCE_URL, `https://github.com/haseab/retrace/archive/${UPSTREAM_SOURCE_COMMIT}.tar.gz`)
  assert.equal(UPSTREAM_SOURCE_SHA256, '604f7f26926e71bfc6d5aebc2a94959cc43532ab91250c49870fa539e559a3d0')
  assert.equal(MACMAN_STALKER_APP_NAME, 'MacMan Stalker')
  assert.equal(MACMAN_STALKER_BUNDLE_ID, 'com.macman.stalker')
  assert.equal(MACMAN_STALKER_SCHEME, 'macman-stalker')
})

test('a staged Stalker payload is the rebranded native app, not an upstream or Python runtime', async () => {
  const inspected = []

  await assert.doesNotReject(
    validateStagedStalkerApp('/staged', {
      inspectApp: async appPath => {
        inspected.push(appPath)

        return {
          bundleIdentifier: 'com.macman.stalker',
          displayName: 'MacMan Stalker',
          executableArchitectures: ['arm64'],
          scheme: 'macman-stalker',
          signed: true,
          updaterFeed: null,
          version: '0.8.7'
        }
      }
    })
  )

  assert.deepEqual(inspected, ['/staged/MacMan Stalker.app'])

  await assert.rejects(
    validateStagedStalkerApp('/staged', {
      inspectApp: async () => ({
        bundleIdentifier: 'com.macman.stalker',
        displayName: 'MacMan Stalker',
        executableArchitectures: ['x86_64'],
        scheme: 'macman-stalker',
        signed: true,
        updaterFeed: null,
        version: '0.8.7'
      })
    }),
    /arm64/i
  )
})
