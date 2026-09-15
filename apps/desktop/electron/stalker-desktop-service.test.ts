import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { afterEach, expect, test, vi } from 'vitest'

import { createStalkerDesktopService } from './stalker-desktop-service'

const directories: string[] = []
afterEach(() => directories.splice(0).forEach(directory => fs.rmSync(directory, { recursive: true, force: true })))

function fixture(open = vi.fn(async () => undefined)) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'macman-stalker-service-'))
  directories.push(directory)
  const native = {
    resolve: () => ({ appPath: '/owned/MacMan Stalker.app', executablePath: '/owned/MacMan' }),
    open,
    running: vi.fn(async () => true),
    stop: vi.fn(async () => undefined)
  }
  const service = createStalkerDesktopService({
    allowDevelopmentFallback: false,
    appRoot: directory,
    enabled: true,
    log: () => undefined,
    resourcesPath: directory,
    userDataPath: directory,
    native
  })
  return { service, native, directory }
}

test('disconnect during native launch cannot leave Stalker running', async () => {
  let release!: () => void
  const opened = new Promise<void>(resolve => { release = resolve })
  const { service, native, directory } = fixture(vi.fn(() => opened))
  const enabling = service.enable()
  await vi.waitFor(() => expect(native.open).toHaveBeenCalledOnce())
  const disabling = service.disable()
  expect(JSON.parse(fs.readFileSync(path.join(directory, 'stalker-consent.json'), 'utf8')).desiredEnabled).toBe(false)
  release()
  await Promise.all([enabling, disabling])
  expect(native.stop).toHaveBeenCalledWith('/owned/MacMan')
  expect(await service.snapshot()).toMatchObject({ desiredEnabled: false, runtimeState: 'off' })
})

test('Stalker is opt-in and reopens its owned timeline after reconnect', async () => {
  const { service, native } = fixture()
  await service.start()
  expect(native.open).not.toHaveBeenCalled()
  await service.enable()
  await service.disable()
  await service.enable()
  await service.openStalker()
  expect(native.open).toHaveBeenLastCalledWith(expect.objectContaining({ appPath: '/owned/MacMan Stalker.app' }), 'timeline')
  expect(await service.snapshot()).toMatchObject({ desiredEnabled: true, runtimeState: 'running' })
})
