import path from 'node:path'

interface MacManBackendSourceOptions {
  resourcesPath: string
  isPackaged: boolean
  isSourceRoot: (candidate: string) => boolean
}

/**
 * Resolve the immutable Python source shipped with MacMan.
 *
 * The managed checkout still owns the Python environment and user state, but
 * it must never own the code executed by a packaged MacMan build: allowing an
 * older checkout to win silently removes MacMan-only RPCs such as the
 * conversational hot path.
 */
export function resolveMacManBackendSource(options: MacManBackendSourceOptions): string | null {
  if (!options.isPackaged || !options.resourcesPath) {
    return null
  }

  const candidate = path.join(options.resourcesPath, 'macman-backend')

  return options.isSourceRoot(candidate) ? candidate : null
}
