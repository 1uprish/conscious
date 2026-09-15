import { execFileSync } from 'node:child_process'
import { chmodSync, copyFileSync, lstatSync, mkdirSync, rmSync } from 'node:fs'
import path from 'node:path'

import { isMain } from './utils.mjs'

const DESKTOP_ROOT = path.resolve(import.meta.dirname, '..')
const REPO_ROOT = path.resolve(DESKTOP_ROOT, '..', '..')
const DEFAULT_OUTPUT_ROOT = path.join(DESKTOP_ROOT, 'build', 'macman-backend')

const RUNTIME_PATHS = [
  '*.py',
  'LICENSE',
  'SOUL.md',
  'cli-config.yaml.example',
  'pyproject.toml',
  'uv.lock',
  'acp_adapter',
  'agent',
  'assets',
  'cron',
  'gateway',
  'hermes',
  'hermes_cli',
  'locales',
  'native',
  'optional-mcps',
  'optional-skills',
  'plugins',
  'providers',
  'skills',
  'tools',
  'tui_gateway'
]

export function trackedRuntimeFiles(repoRoot = REPO_ROOT) {
  const output = execFileSync('git', ['ls-files', '-z', '--', ...RUNTIME_PATHS], {
    cwd: repoRoot,
    encoding: 'buffer',
    stdio: ['ignore', 'pipe', 'inherit']
  })

  return output
    .toString('utf8')
    .split('\0')
    .filter(Boolean)
}

export function stageMacManBackend({ repoRoot = REPO_ROOT, outputRoot = DEFAULT_OUTPUT_ROOT } = {}) {
  const files = trackedRuntimeFiles(repoRoot)

  rmSync(outputRoot, { recursive: true, force: true })
  for (const relativePath of files) {
    const source = path.join(repoRoot, relativePath)
    const destination = path.join(outputRoot, relativePath)
    const stat = lstatSync(source)

    mkdirSync(path.dirname(destination), { recursive: true })
    copyFileSync(source, destination)
    chmodSync(destination, stat.mode)
  }

  return { files: files.length, outputRoot }
}

if (isMain(import.meta.url)) {
  const result = stageMacManBackend()
  console.log(`[stage-macman-backend] staged ${result.files} tracked runtime files at ${result.outputRoot}`)
}
