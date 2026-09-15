import { useCallback, useEffect, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Eye, RefreshCw } from '@/lib/icons'

export type MacManStalkerSnapshot = {
  archiveBytes: number
  desiredEnabled: boolean
  lastError?: string
  manuallyPaused: boolean
  runtimeState: 'failed' | 'off' | 'running' | 'starting'
}

const UNAVAILABLE: MacManStalkerSnapshot = {
  archiveBytes: 0,
  desiredEnabled: false,
  lastError: 'This MacMan build does not include the native Stalker companion.',
  manuallyPaused: false,
  runtimeState: 'failed'
}

const STATUS = {
  failed: 'Unavailable',
  off: 'Off',
  running: 'Running',
  starting: 'Starting'
} satisfies Record<MacManStalkerSnapshot['runtimeState'], string>

export function MacManStalker() {
  const [snapshot, setSnapshot] = useState<MacManStalkerSnapshot | null>(null)
  const [busy, setBusy] = useState(false)

  const refresh = useCallback(async () => {
    const bridge = window.hermesDesktop.stalker
    if (!bridge) {
      setSnapshot(UNAVAILABLE)
      return
    }
    try { setSnapshot(await bridge.snapshot()) }
    catch (error) {
      setSnapshot({ ...UNAVAILABLE, lastError: error instanceof Error ? error.message : String(error) })
    }
  }, [])

  useEffect(() => { void refresh() }, [refresh])

  async function run(action: 'disable' | 'enable' | 'open' | 'retry') {
    const bridge = window.hermesDesktop.stalker
    if (!bridge) {return}
    setBusy(true)
    try {
      if (action === 'open') {
        await bridge.open()
        await refresh()
      } else {
        setSnapshot(await bridge[action]())
      }
    } finally {
      setBusy(false)
    }
  }

  const state = snapshot?.runtimeState ?? 'starting'
  const enabled = snapshot?.desiredEnabled === true

  return (
    <div className="mm-inset-card mm-stalker-card">
      <span className="mm-row-symbol"><Eye aria-hidden /></span>
      <span className="mm-row-copy">
        <strong>Stalker</strong>
        <small>Private native screen history, stored and searched locally on this Mac.</small>
        {snapshot?.lastError ? <small className="mm-stalker-error">{snapshot.lastError}</small> : null}
      </span>
      <span className="mm-stalker-actions">
        <span className={`mm-status-badge is-${state === 'running' ? 'ready' : state === 'failed' ? 'unavailable' : 'optional'}`}>
          {STATUS[state]}
        </span>
        {state === 'failed' && window.hermesDesktop.stalker ? (
          <Button aria-label="Retry Stalker" disabled={busy} onClick={() => void run('retry')} size="sm" variant="outline">
            <RefreshCw /> Retry
          </Button>
        ) : enabled ? (
          <>
            <Button aria-label="Open Stalker" disabled={busy} onClick={() => void run('open')} size="sm" variant="outline">Open</Button>
            <Button aria-label="Turn off Stalker" disabled={busy} onClick={() => void run('disable')} size="sm" variant="outline">Turn off</Button>
          </>
        ) : (
          <Button aria-label="Turn on Stalker" disabled={busy} onClick={() => void run('enable')} size="sm">Turn on</Button>
        )}
      </span>
    </div>
  )
}
