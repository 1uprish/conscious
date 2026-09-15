import { execFile } from 'node:child_process'
import { createHash } from 'node:crypto'
import { createWriteStream } from 'node:fs'
import { access, cp, mkdir, mkdtemp, readFile, readdir, rename, rm, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { pipeline } from 'node:stream/promises'
import { promisify } from 'node:util'

const execFileAsync = promisify(execFile)

export const UPSTREAM_SOURCE_COMMIT = 'd9313842f2e752b4f8ddaa572b4a22fdbbfac7c2'
export const UPSTREAM_SOURCE_URL = `https://github.com/haseab/retrace/archive/${UPSTREAM_SOURCE_COMMIT}.tar.gz`
export const UPSTREAM_SOURCE_SHA256 = '604f7f26926e71bfc6d5aebc2a94959cc43532ab91250c49870fa539e559a3d0'
export const MACMAN_STALKER_APP_NAME = 'MacMan Stalker'
export const MACMAN_STALKER_BUNDLE_ID = 'com.macman.stalker'
export const MACMAN_STALKER_SCHEME = 'macman-stalker'
const SUPPORT_URL = 'https://github.com/1uprish/macman/issues'

export function isSupportedStalkerPack(context) {
  return context?.electronPlatformName === 'darwin' && context?.productFilename === 'MacMan' && context?.architecture === 'arm64'
}

function replaceSection(source, start, end, replacement) {
  const startAt = source.indexOf(start)
  const endAt = source.indexOf(end, startAt + start.length)
  if (startAt < 0 || endAt < 0) {throw new Error(`Pinned Stalker source no longer contains ${start}`)}
  return source.slice(0, startAt) + replacement + source.slice(endAt)
}

/** The pinned fork owns its identity, not the user's existing upstream installation. */
export function rebrandStalkerSourceText(relativePath, source) {
  let branded = source
    .replaceAll('io.retrace.app', MACMAN_STALKER_BUNDLE_ID)
    .replaceAll('io.retrace', MACMAN_STALKER_BUNDLE_ID)
    .replaceAll('com.retrace.database', `${MACMAN_STALKER_BUNDLE_ID}.database`)
    .replaceAll('/Applications/Retrace.app', `/Applications/${MACMAN_STALKER_APP_NAME}.app`)
    .replaceAll('~/Library/Application Support/Retrace', '~/Library/Application Support/MacMan/Stalker')
    .replaceAll('/Library/Logs/Retrace', '/Library/Logs/MacMan/Stalker')
    .replaceAll('retrace://', `${MACMAN_STALKER_SCHEME}://`)
    .replaceAll('https://github.com/haseab/retrace', 'https://github.com/1uprish/macman')
    .replace(/https:\/\/retrace\.to[^"\s<]*/g, SUPPORT_URL)
    .replace(/https:\/\/dub\.sh\/(?:haseab-twitter|support-haseab|support-retrace-[^"\s<]*|retrace-discord)/g, SUPPORT_URL)
    .replaceAll('@haseab on X', 'MacMan Support')
    .replaceAll('@haseab', 'MacMan')
    .replaceAll('Text("Haseab")', 'Text("MacMan")')
    .replaceAll('Creator of Retrace', 'Private screen memory')
    .replaceAll('Support Me', 'Get Help')
    .replaceAll('Chat with me on retrace.to', 'Open MacMan support')
    .replaceAll('RETRACE', 'MACMAN')
    .replaceAll('Retrace', 'MacMan')
    .replaceAll('retrace', 'macman')

  // Packaged .apps load a compiled catalog from Contents/Resources, not the
  // SwiftPM accessor's build-machine fallback path.
  if (['UI/Views/Onboarding/OnboardingView.swift', 'UI/Components/MilestoneCelebrationView.swift', 'UI/Views/Settings/Sections/SettingsFeedbackActions.swift'].includes(relativePath)) {
    branded = branded.replace(/#if SWIFT_PACKAGE\n[\s\S]*?\n#endif/g, block => block.includes('Bundle.module') ? '' : block)
  }

  if (relativePath === 'UI/Components/DeeplinkHandler.swift') {
    branded = branded.replaceAll('"macman"', `"${MACMAN_STALKER_SCHEME}"`)
  }
  if (relativePath === 'UI/Components/UpdaterManager.swift') {
    branded = replaceSection(branded, '    public func initialize() {', '    // MARK: - Public Methods',
      '    public func initialize() {\n        // The parent MacMan app updates this companion atomically with its runtime.\n        canCheckForUpdates = false\n        automaticUpdateChecksEnabled = false\n    }\n\n')
    branded = replaceSection(branded, '    private var appcastFeedURL: URL? {', '    private func loadCachedChangelogIfAvailable()',
      '    private var appcastFeedURL: URL? { nil }\n\n')
  }
  if (relativePath === 'UI/Views/Feedback/FeedbackService.swift') {
    branded = replaceSection(branded, '    public func submitFeedback(_ submission: FeedbackSubmission) async throws -> Bool {', '    // MARK: - Screenshot',
      '    public func submitFeedback(_ submission: FeedbackSubmission) async throws -> Bool {\n        // Diagnostics must never be uploaded to an upstream vendor by the branded fork.\n        throw FeedbackError.networkError("Reports are managed by MacMan. Export this report and open MacMan support.")\n    }\n\n')
  }
  if (relativePath === 'UI/Views/Feedback/FeedbackFormView.swift') {
    branded = branded.replaceAll('await viewModel.submit()', 'await viewModel.exportFeedbackReport()')
      .replaceAll('Send Feedback', 'Export Report')
  }
  if (relativePath === 'UI/Views/Dashboard/DashboardView.swift') {
    branded = 'import ScreenCaptureKit\n' + branded
    branded = branded.replace(
      'SystemSettingsOpener.openAccessibilitySettings()',
      `let options: NSDictionary = [
                            kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true
                        ]
                        _ = AXIsProcessTrustedWithOptions(options)
                        SystemSettingsOpener.openAccessibilitySettings()`
    )
    branded = branded.replace(
      'SystemSettingsOpener.openScreenRecordingSettings()',
      `Task { @MainActor in
                            do {
                                _ = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: false)
                            } catch {
                                Log.warning("[MacMan Stalker] Screen Recording request failed: \\(error)", category: .ui)
                                SystemSettingsOpener.openScreenRecordingSettings()
                            }
                        }`
    )
  }
  if (relativePath === 'UI/Views/Onboarding/OnboardingView.swift') {
    branded = replaceSection(branded, '    private var macmanLogo: some View {', '    /// Rewind logo rendered',
      '    private var macmanLogo: some View {\n        Image(nsImage: NSApp.applicationIconImage)\n            .resizable()\n            .scaledToFit()\n    }\n\n')
    branded = branded.replaceAll('Text("H")', 'Text("M")')
  }
  if (relativePath === 'UI/Views/Settings/Sections/GeneralSettingsView.swift') {
    branded = replaceSection(branded, '    @ViewBuilder\n    var updatesCard: some View {', '    @ViewBuilder\n    var startupCard',
      `    @ViewBuilder
    var updatesCard: some View {
        ModernSettingsCard(title: "Updates", icon: "arrow.down.circle") {
            Text("MacMan Stalker \\(BuildInfo.displayVersion)")
                .font(.macmanCalloutMedium)
                .foregroundColor(.macmanPrimary)
            Text("Updates are managed by MacMan. This companion updates with the main app.")
                .font(.macmanCaption2)
                .foregroundColor(.macmanSecondary)
        }
    }

`)
  }
  if (relativePath === 'UI/Components/MenuBarManager.swift') {
    branded = replaceSection(branded, '        // Check for updates', '        // Get Help', '')
    branded = replaceSection(branded, '    @objc private func openFeedback() {', '    @objc private func checkForUpdatesFromMenu()',
      `    @objc private func openFeedback() {
        if let url = URL(string: "${SUPPORT_URL}") { NSWorkspace.shared.open(url) }
    }

`)
    branded = branded.replaceAll('button.image?.isTemplate = true', 'button.image?.isTemplate = false')
    branded = replaceSection(
      branded,
      '    /// Create a custom status icon with two triangles (MacMan logo)',
      '    /// Create a custom view with a toggle switch for recording',
      `    /// Create a native menu bar icon from MacMan's application identity.
    /// Recording and paused states retain a small, glanceable status badge.
    private func createStatusIcon(style: RecordingStatusIconStyle, scale: CGFloat = 1.0) -> NSImage {
        let canvasSize = NSSize(width: 22, height: 18)
        let image = NSImage(size: canvasSize)
        let baseIconSide: CGFloat = 16
        let iconSide = max(5, baseIconSide * scale)
        let iconRect = NSRect(
            x: 1 + (baseIconSide - iconSide) / 2,
            y: 1 + (baseIconSide - iconSide) / 2,
            width: iconSide,
            height: iconSide
        )

        image.lockFocus()
        NSApp.applicationIconImage.draw(
            in: iconRect,
            from: .zero,
            operation: .sourceOver,
            fraction: 1
        )

        let badgeColor: NSColor?
        switch style {
        case .recording:
            badgeColor = .systemRed
        case .paused:
            badgeColor = .systemOrange
        case .off:
            badgeColor = nil
        }

        if let badgeColor {
            NSColor.black.withAlphaComponent(0.65).setFill()
            NSBezierPath(ovalIn: NSRect(x: 16, y: 1, width: 6, height: 6)).fill()
            badgeColor.setFill()
            NSBezierPath(ovalIn: NSRect(x: 17, y: 2, width: 4, height: 4)).fill()
        }

        image.unlockFocus()
        image.isTemplate = false
        return image
    }

`)
  }
  if (relativePath === 'UI/RetraceApp.swift') {
    branded = replaceSection(branded, '        let checkForUpdatesItem = makeMainMenuItem(', '        menu.addItem(.separator())', '')
    branded = branded.replace('    private func handleDeeplink(_ url: URL) {', `    private func handleDeeplink(_ url: URL) {
        if url.scheme == "${MACMAN_STALKER_SCHEME}", url.host == "disconnect" {
            Task { @MainActor in
                do {
                    if SMAppService.mainApp.status == .enabled { try await SMAppService.mainApp.unregister() }
                    await CrashRecoveryManager.shared.prepareForExpectedExit()
                    // AppKit termination runs a nested loop. Enter from the
                    // run loop, not a Swift task holding the main executor;
                    // the async termination flush must be able to run there.
                    RunLoop.main.perform(inModes: [.default, .eventTracking]) {
                        self.requestImmediateTermination(skipQuitConfirmation: true)
                    }
                } catch {
                    Log.error("[MacMan] Disconnect failed: \\(error)", category: .app)
                }
            }
            return
        }`)
    branded = 'import ServiceManagement\n' + branded
  }
  return branded
}

async function rebrandSourceTree(root, desktopRoot) {
  async function visit(directory) {
    for (const entry of await readdir(directory, { withFileTypes: true })) {
      const entryPath = path.join(directory, entry.name)
      if (entry.isDirectory()) {
        if (!['.git', '.build'].includes(entry.name)) {await visit(entryPath)}
      } else if (/\.(swift|plist|entitlements)$/.test(entry.name)) {
        const relativePath = path.relative(root, entryPath).split(path.sep).join('/')
        await writeFile(entryPath, rebrandStalkerSourceText(relativePath, await readFile(entryPath, 'utf8')))
      }
      const brandedName = entry.name.replaceAll('Retrace', 'MacMan').replaceAll('retrace', 'macman')
        .replaceAll('io.macman.app', MACMAN_STALKER_BUNDLE_ID)
      if (brandedName !== entry.name) {await rename(entryPath, path.join(directory, brandedName))}
    }
  }
  await visit(root)
  await cp(path.join(desktopRoot, 'assets', 'icon.png'), path.join(root, 'UI', 'Assets.xcassets', 'CreatorProfile.imageset', 'haseab.png'))
  await rm(path.join(root, 'UI', 'Assets.xcassets', 'CreatorProfile.imageset', 'haseab.webp'), { force: true })
  await rm(path.join(root, 'UI', 'Assets.xcassets', 'AppIcon.appiconset'), { recursive: true, force: true })
}

async function sha256(filePath) {
  return createHash('sha256').update(await readFile(filePath)).digest('hex')
}

async function ensurePinnedArchive(cachePath) {
  const cacheRoot = path.dirname(cachePath)
  await mkdir(cacheRoot, { recursive: true })
  for (const entry of await readdir(cacheRoot)) {
    const candidate = path.join(cacheRoot, entry)
    if (candidate !== cachePath) {await rm(candidate, { force: true, recursive: true })}
  }
  try {
    if (await sha256(cachePath) === UPSTREAM_SOURCE_SHA256) {return}
  } catch (error) {
    if (error.code !== 'ENOENT') {throw error}
  }
  await rm(cachePath, { force: true })
  const partial = `${cachePath}.partial-${process.pid}`
  const response = await fetch(UPSTREAM_SOURCE_URL, { redirect: 'follow' })
  if (!response.ok || !response.body) {throw new Error(`Stalker source download failed with HTTP ${response.status}`)}
  try {
    await pipeline(response.body, createWriteStream(partial, { mode: 0o600 }))
    const digest = await sha256(partial)
    if (digest !== UPSTREAM_SOURCE_SHA256) {throw new Error(`Stalker checksum ${digest} does not match pinned ${UPSTREAM_SOURCE_SHA256}`)}
    await rename(partial, cachePath)
  } finally {
    await rm(partial, { force: true })
  }
}

async function plistValue(infoPlist, key, optional = false) {
  try {
    const { stdout } = await execFileAsync('/usr/libexec/PlistBuddy', ['-c', `Print :${key}`, infoPlist])
    return stdout.trim()
  } catch (error) {
    if (optional) {return null}
    throw error
  }
}

async function inspectNativeApp(appPath) {
  const infoPlist = path.join(appPath, 'Contents', 'Info.plist')
  const executable = path.join(appPath, 'Contents', 'MacOS', 'MacMan')
  await access(path.join(appPath, 'Contents', 'Resources', 'Assets.car'))
  const { stdout: architectures } = await execFileAsync('/usr/bin/lipo', ['-archs', executable])
  await execFileAsync('/usr/bin/codesign', ['--verify', '--deep', '--strict', appPath])
  return {
    bundleIdentifier: await plistValue(infoPlist, 'CFBundleIdentifier'),
    displayName: await plistValue(infoPlist, 'CFBundleDisplayName'),
    executableArchitectures: architectures.trim().split(/\s+/).filter(Boolean),
    scheme: await plistValue(infoPlist, 'CFBundleURLTypes:0:CFBundleURLSchemes:0'),
    signed: true,
    updaterFeed: await plistValue(infoPlist, 'SUFeedURL', true),
    version: await plistValue(infoPlist, 'CFBundleShortVersionString')
  }
}

export async function validateStagedStalkerApp(payloadRoot, inspectors = { inspectApp: inspectNativeApp }) {
  const inspected = await inspectors.inspectApp(path.join(payloadRoot, `${MACMAN_STALKER_APP_NAME}.app`))
  if (inspected.bundleIdentifier !== MACMAN_STALKER_BUNDLE_ID || inspected.displayName !== MACMAN_STALKER_APP_NAME || inspected.scheme !== MACMAN_STALKER_SCHEME) {
    throw new Error('Expected the native companion to use the complete MacMan Stalker identity')
  }
  if (inspected.version !== '0.8.7') {throw new Error(`Expected native Stalker v0.8.7, got ${inspected.version}`)}
  if (!inspected.executableArchitectures.includes('arm64')) {throw new Error('Expected an arm64 native Stalker app')}
  if (!inspected.signed) {throw new Error('Expected a valid native Stalker signature')}
  if (inspected.updaterFeed) {throw new Error('Stalker updates must be owned by the parent MacMan app')}
}

export async function stageMacManStalker(desktopRoot) {
  const cachePath = path.join(desktopRoot, 'build', 'stalker-cache', `native-source-${UPSTREAM_SOURCE_SHA256}.tar.gz`)
  const outputRoot = path.join(desktopRoot, 'build', 'macman-stalker')
  const fingerprint = createHash('sha256').update(await readFile(new URL(import.meta.url))).update(await readFile(path.join(desktopRoot, 'assets', 'icon.png'))).update(await readFile(path.join(desktopRoot, 'assets', 'icon.icns'))).digest('hex')
  try {
    if ((await readFile(path.join(outputRoot, 'build-fingerprint'), 'utf8')) === fingerprint) {
      await validateStagedStalkerApp(outputRoot)
      return outputRoot
    }
  } catch (error) {
    if (error.code !== 'ENOENT') {console.log('[stalker] cached payload failed validation; rebuilding')}
  }
  await mkdir(path.join(desktopRoot, 'build'), { recursive: true })
  const temporaryRoot = await mkdtemp(path.join(desktopRoot, 'build', 'macman-stalker-native-'))
  const sourceRoot = path.join(temporaryRoot, 'source')
  const appPath = path.join(temporaryRoot, 'payload', `${MACMAN_STALKER_APP_NAME}.app`)
  const contents = path.join(appPath, 'Contents')
  try {
    await ensurePinnedArchive(cachePath)
    await mkdir(sourceRoot)
    await execFileAsync('/usr/bin/tar', ['-xzf', cachePath, '-C', sourceRoot, '--strip-components', '1'])
    await rebrandSourceTree(sourceRoot, desktopRoot)
    console.log('[stalker] compiling pinned MacMan native screen-memory companion')
    await execFileAsync('/usr/bin/swift', ['build', '-c', 'release', '--product', 'MacMan'], { cwd: sourceRoot, maxBuffer: 32 * 1024 * 1024 })
    await execFileAsync('/usr/bin/swift', ['build', '-c', 'release', '--product', 'MacManCrashRecoveryHelper'], { cwd: sourceRoot, maxBuffer: 16 * 1024 * 1024 })
    const { stdout } = await execFileAsync('/usr/bin/swift', ['build', '-c', 'release', '--show-bin-path'], { cwd: sourceRoot })
    const binPath = stdout.trim()
    await Promise.all(['MacOS', 'Resources', 'Frameworks', 'Library/Helpers', 'Library/LaunchAgents'].map(directory => mkdir(path.join(contents, directory), { recursive: true })))
    await cp(path.join(binPath, 'MacMan'), path.join(contents, 'MacOS', 'MacMan'))
    await cp(path.join(binPath, 'MacManCrashRecoveryHelper'), path.join(contents, 'Library', 'Helpers', 'MacManCrashRecoveryHelper'))
    await cp(path.join(binPath, 'Sparkle.framework'), path.join(contents, 'Frameworks', 'Sparkle.framework'), { recursive: true, verbatimSymlinks: true })
    await execFileAsync('/usr/bin/xcrun', ['actool', '--compile', path.join(contents, 'Resources'), '--platform', 'macosx', '--minimum-deployment-target', '13.0', path.join(sourceRoot, 'UI', 'Assets.xcassets')], { maxBuffer: 8 * 1024 * 1024 })
    await cp(path.join(desktopRoot, 'assets', 'icon.icns'), path.join(contents, 'Resources', 'AppIcon.icns'))
    await cp(path.join(sourceRoot, 'LICENSE'), path.join(contents, 'Resources', 'THIRD_PARTY_LICENSE-Retrace.txt'))
    await cp(path.join(sourceRoot, 'UI', 'LaunchAgents', `${MACMAN_STALKER_BUNDLE_ID}.crash-recovery.plist`), path.join(contents, 'Library', 'LaunchAgents', `${MACMAN_STALKER_BUNDLE_ID}.crash-recovery.plist`))
    let plist = await readFile(path.join(sourceRoot, 'UI', 'Info.plist'), 'utf8')
    plist = plist.replaceAll('$(MARKETING_VERSION)', '0.8.7').replaceAll('$(CURRENT_PROJECT_VERSION)', '87')
      .replace(/<key>SU[^<]+<\/key>\s*<(?:string|integer)>[^<]*<\/(?:string|integer)>/g, '')
      .replace(/<key>SU[^<]+<\/key>\s*<(?:true|false)\s*\/>/g, '')
    const infoPlist = path.join(contents, 'Info.plist')
    await writeFile(infoPlist, plist)
    for (const [key, value] of Object.entries({ CFBundleDisplayName: MACMAN_STALKER_APP_NAME, CFBundleName: MACMAN_STALKER_APP_NAME, 'CFBundleURLTypes:0:CFBundleURLSchemes:0': MACMAN_STALKER_SCHEME })) {
      await execFileAsync('/usr/libexec/PlistBuddy', ['-c', `Set :${key} ${value}`, infoPlist])
    }
    await execFileAsync('/usr/bin/install_name_tool', ['-add_rpath', '@executable_path/../Frameworks', path.join(contents, 'MacOS', 'MacMan')])
    await execFileAsync('/usr/bin/codesign', ['--force', '--deep', '--sign', '-', '--entitlements', path.join(sourceRoot, 'UI', 'MacMan.entitlements'), appPath])
    await validateStagedStalkerApp(path.dirname(appPath))
    await writeFile(path.join(path.dirname(appPath), 'build-fingerprint'), fingerprint)
    // Retain the last valid payload until its replacement has compiled and validated.
    await rm(outputRoot, { force: true, recursive: true })
    await rename(path.dirname(appPath), outputRoot)
    return outputRoot
  } catch (error) {
    if (error.stdout) {
      const lines = error.stdout.split('\n')
      console.error(lines.filter((line, index) => /error:/.test(line) || lines.slice(Math.max(0, index - 3), index).some(previous => /error:/.test(previous))).join('\n'))
    }
    throw error
  } finally {
    await rm(temporaryRoot, { force: true, recursive: true })
  }
}
