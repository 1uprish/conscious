import { execFile } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { promisify } from 'node:util'

const execFileAsync = promisify(execFile)
const launchServicesRegister = '/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister'

export interface StalkerNativePathIo {
  isDirectory(candidate: string): boolean
  isExecutable(candidate: string): boolean
}

export interface StalkerNativeApp {
  appPath: string
  executablePath: string
}

export type StalkerNativeView = 'dashboard' | 'search' | 'timeline'

const realPathIo: StalkerNativePathIo = {
  isDirectory(candidate) {
    try {
      return fs.lstatSync(candidate).isDirectory() && fs.realpathSync(candidate) === path.resolve(candidate)
    } catch {
      return false
    }
  },
  isExecutable(candidate) {
    try {
      const stat = fs.lstatSync(candidate)
      if (!stat.isFile() || stat.isSymbolicLink() || fs.realpathSync(candidate) !== path.resolve(candidate)) {return false}
      fs.accessSync(candidate, fs.constants.X_OK)
      return true
    } catch {
      return false
    }
  }
}

export interface ResolveStalkerAppOptions {
  allowDevelopmentFallback: boolean
  appRoot: string
  architecture: string
  io?: StalkerNativePathIo
  resourcesPath: string
}

export function resolveStalkerApp(options: ResolveStalkerAppOptions): StalkerNativeApp | null {
  if (options.architecture !== 'arm64') {return null}
  const io = options.io ?? realPathIo
  const candidates = [path.join(options.resourcesPath, 'stalker', 'MacMan Stalker.app')]
  if (options.allowDevelopmentFallback) {
    candidates.push(path.join(options.appRoot, 'build', 'macman-stalker', 'MacMan Stalker.app'))
  }
  for (const appPath of candidates) {
    const executablePath = path.join(appPath, 'Contents', 'MacOS', 'MacMan')
    if (io.isDirectory(appPath) && io.isExecutable(executablePath)) {return { appPath, executablePath }}
  }
  return null
}

export function buildStalkerOpenRequest(appPath: string, view: StalkerNativeView) {
  const route = view === 'timeline' ? 'macman-stalker://timeline' : view === 'search' ? 'macman-stalker://search' : undefined
  return { args: ['-a', appPath, ...(route ? [route] : [])], command: '/usr/bin/open' }
}

export function buildStalkerLaunchRequests(appPath: string, view: StalkerNativeView) {
  return [
    { args: ['-f', appPath], command: launchServicesRegister },
    buildStalkerOpenRequest(appPath, view)
  ]
}

export async function openStalkerNativeApp(
  app: StalkerNativeApp,
  view: StalkerNativeView,
  options: { background?: boolean } = {}
): Promise<void> {
  for (const request of buildStalkerLaunchRequests(app.appPath, view)) {
    const args = options.background && request.command === '/usr/bin/open' ? ['-g', ...request.args] : request.args
    await execFileAsync(request.command, args)
  }
}

export async function stalkerNativePids(executablePath: string): Promise<number[]> {
  const { stdout } = await execFileAsync('/bin/ps', ['-axo', 'pid=,command='])
  const resolvedExecutable = path.resolve(executablePath)
  return stdout
    .split('\n')
    .map(line => line.trim().match(/^(\d+)\s+(.+)$/))
    .filter((match): match is RegExpMatchArray => Boolean(match))
    .filter(match => match[2] === resolvedExecutable || match[2].startsWith(`${resolvedExecutable} `))
    .map(match => Number(match[1]))
    .filter(Number.isSafeInteger)
}

export async function isStalkerNativeAppRunning(executablePath: string): Promise<boolean> {
  return (await stalkerNativePids(executablePath)).length > 0
}

export async function stopStalkerNativeApp(executablePath: string): Promise<void> {
  const pids = await stalkerNativePids(executablePath)
  if (pids.length === 0) {return}
  const appPath = path.resolve(executablePath, '..', '..', '..')
  await execFileAsync('/usr/bin/open', ['-g', '-a', appPath, 'macman-stalker://disconnect'])
  const deadline = Date.now() + 15_000
  while (Date.now() < deadline) {
    if ((await stalkerNativePids(executablePath)).length === 0) {return}
    await new Promise(resolve => setTimeout(resolve, 100))
  }
  throw new Error('MacMan Stalker has not finished disconnecting. Retry after it finishes starting; recording may still be active.')
}
