import fs from 'node:fs'
import path from 'node:path'

import {
  isStalkerNativeAppRunning,
  openStalkerNativeApp,
  resolveStalkerApp,
  stopStalkerNativeApp,
  type StalkerNativeApp
} from './stalker-native-app'

export type StalkerRuntimeState = 'failed' | 'off' | 'running' | 'starting'

export interface StalkerSnapshot {
  archiveBytes: number
  desiredEnabled: boolean
  lastError?: string
  manuallyPaused: boolean
  pid?: number
  runtimeState: StalkerRuntimeState
}

interface StalkerConsent { desiredEnabled: boolean }
const CONSENT_FILE = 'stalker-consent.json'

function readConsent(filePath: string): StalkerConsent {
  try { return { desiredEnabled: JSON.parse(fs.readFileSync(filePath, 'utf8'))?.desiredEnabled === true } }
  catch { return { desiredEnabled: false } }
}

function writeConsent(filePath: string, consent: StalkerConsent): void {
  fs.mkdirSync(path.dirname(filePath), { recursive: true, mode: 0o700 })
  const temporary = `${filePath}.tmp`
  fs.rmSync(temporary, { force: true })
  fs.writeFileSync(temporary, `${JSON.stringify(consent, null, 2)}\n`, { encoding: 'utf8', mode: 0o600 })
  fs.renameSync(temporary, filePath)
}

export interface StalkerDesktopServiceOptions {
  allowDevelopmentFallback: boolean
  appRoot: string
  enabled: boolean
  log(message: string): void
  resourcesPath: string
  userDataPath: string
  native?: {
    resolve: typeof resolveStalkerApp
    open: typeof openStalkerNativeApp
    running: typeof isStalkerNativeAppRunning
    stop: typeof stopStalkerNativeApp
  }
}

export function createStalkerDesktopService(options: StalkerDesktopServiceOptions) {
  const native = options.native ?? {
    resolve: resolveStalkerApp,
    open: openStalkerNativeApp,
    running: isStalkerNativeAppRunning,
    stop: stopStalkerNativeApp
  }
  const consentPath = path.join(options.userDataPath, CONSENT_FILE)
  let consent = readConsent(consentPath)
  let nativeApp: StalkerNativeApp | null = null
  let startPromise: Promise<void> | null = null
  let snapshotValue: StalkerSnapshot = {
    archiveBytes: 0,
    desiredEnabled: consent.desiredEnabled,
    manuallyPaused: false,
    runtimeState: consent.desiredEnabled ? 'starting' : 'off'
  }

  const snapshot = (): StalkerSnapshot => ({ ...snapshotValue })
  function publish(patch: Partial<StalkerSnapshot>): StalkerSnapshot {
    snapshotValue = { ...snapshotValue, ...patch, desiredEnabled: consent.desiredEnabled, manuallyPaused: false }
    return snapshot()
  }
  function persist(next: StalkerConsent): void {
    consent = { ...next }
    writeConsent(consentPath, consent)
  }
  function requireNativeApp(): StalkerNativeApp {
    if (!nativeApp) {throw new Error('The native Stalker app is unavailable or incomplete in this MacMan build.')}
    return nativeApp
  }

  async function start(): Promise<void> {
    if (!options.enabled) {return}
    if (!startPromise) {
      startPromise = Promise.resolve().then(async () => {
        nativeApp = native.resolve({
          allowDevelopmentFallback: options.allowDevelopmentFallback,
          appRoot: options.appRoot,
          architecture: process.arch,
          resourcesPath: options.resourcesPath
        })
        if (!nativeApp) {
          publish({ lastError: 'The native Stalker app is unavailable or incomplete in this MacMan build.', runtimeState: 'failed' })
          throw new Error(snapshotValue.lastError)
        }
        if (!consent.desiredEnabled) {
          publish({ lastError: undefined, runtimeState: 'off' })
          return
        }
        const app = nativeApp
        await native.open(app, 'dashboard', { background: true })
        if (!consent.desiredEnabled) {
          await native.stop(app.executablePath)
          publish({ lastError: undefined, runtimeState: 'off' })
          return
        }
        publish({ lastError: undefined, runtimeState: 'running' })
        options.log('[stalker] native MacMan Stalker companion started in the background')
      }).catch(error => {
        startPromise = null
        publish({ lastError: error instanceof Error ? error.message : String(error), runtimeState: 'failed' })
        throw error
      })
    }
    return startPromise
  }

  async function ensureStarted(): Promise<StalkerNativeApp> {
    await start()
    return requireNativeApp()
  }

  async function enable(): Promise<StalkerSnapshot> {
    persist({ desiredEnabled: true })
    publish({ lastError: undefined, runtimeState: 'starting' })
    const app = await ensureStarted()
    if (!consent.desiredEnabled) {return snapshot()}
    await native.open(app, 'dashboard')
    if (!consent.desiredEnabled) {
      await native.stop(app.executablePath)
      return publish({ lastError: undefined, runtimeState: 'off' })
    }
    return publish({ lastError: undefined, runtimeState: 'running' })
  }

  async function disable(): Promise<StalkerSnapshot> {
    persist({ desiredEnabled: false })
    await startPromise?.catch(() => undefined)
    if (consent.desiredEnabled) {return snapshot()}
    if (nativeApp) {
      try { await native.stop(nativeApp.executablePath) }
      catch (error) {
        publish({ lastError: error instanceof Error ? error.message : String(error), runtimeState: 'failed' })
        throw error
      }
    }
    return publish({ lastError: undefined, runtimeState: 'off' })
  }

  async function openStalker(): Promise<void> {
    if (!consent.desiredEnabled) {throw new Error('Turn on Stalker before opening its timeline.')}
    const app = await ensureStarted()
    if (!consent.desiredEnabled) {return}
    await native.open(app, 'timeline')
    if (!consent.desiredEnabled) {await native.stop(app.executablePath)}
  }

  async function refresh(): Promise<StalkerSnapshot> {
    await start().catch(() => undefined)
    if (!nativeApp || !consent.desiredEnabled) {return snapshot()}
    const running = await native.running(nativeApp.executablePath)
    if (!consent.desiredEnabled) {return snapshot()}
    return publish({
      lastError: running ? undefined : 'Stalker stopped. Open it to continue recording.',
      runtimeState: running ? 'running' : 'failed'
    })
  }

  return {
    disable,
    enable,
    openStalker,
    refresh,
    async retry(): Promise<StalkerSnapshot> { startPromise = null; return enable() },
    async snapshot(): Promise<StalkerSnapshot> { return refresh() },
    start,
    async stop(): Promise<void> {
      try { await startPromise } catch { /* failure is already in the snapshot */ }
      if (nativeApp && consent.desiredEnabled) {await native.stop(nativeApp.executablePath)}
    }
  }
}

export type StalkerDesktopService = ReturnType<typeof createStalkerDesktopService>
