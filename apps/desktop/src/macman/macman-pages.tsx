import { useStore } from '@nanostores/react'
import { type ReactNode, useCallback, useEffect, useRef, useState } from 'react'

import { MessagingView } from '@/app/messaging'
import { SkillsView } from '@/app/skills'
import { ConfigSettings } from '@/app/settings/config-settings'
import { NotificationsSettings } from '@/app/settings/notifications-settings'
import { type ProviderView, ProvidersSettings } from '@/app/settings/providers-settings'
import { ComputerUsePanel } from '@/app/settings/computer-use-panel'
import { Button } from '@/components/ui/button'
import { SegmentedControl } from '@/components/ui/segmented-control'
import { getComputerUseStatus, getGlobalModelInfo, getMemoryStatus, getMessagingPlatforms } from '@/hermes'
import {
  AlertTriangle,
  Bell,
  Brain,
  ChevronRight,
  Eye,
  Info,
  Lock,
  MessageCircle,
  Mic,
  Monitor,
  RefreshCw,
  ShieldLock,
  Zap
} from '@/lib/icons'
import { $desktopVersion, refreshDesktopVersion } from '@/store/updates'
import { $gatewayState } from '@/store/session'

import { DEFERRED_MACMAN_CAPABILITIES, type MacManView } from './navigation'

type DetailView = Exclude<MacManView, 'chat'>

interface MacManPagesProps {
  onNavigate: (view: MacManView) => void
  view: DetailView
}

export interface SetupSnapshot {
  computer: 'checking' | 'ready' | 'needs-setup' | 'unavailable'
  memory: 'checking' | 'ready' | 'needs-setup'
  messaging: 'checking' | 'ready' | 'optional'
  model: 'checking' | 'ready' | 'needs-setup'
}

const INITIAL_SETUP: SetupSnapshot = {
  computer: 'checking',
  memory: 'checking',
  messaging: 'checking',
  model: 'checking'
}

export interface SetupSignals {
  computer?: {
    platform_supported?: boolean
    ready?: boolean | null
  }
  memory?: {
    active?: boolean | string
  }
  messaging?: Array<{
    enabled?: boolean
    state?: string | null
  }>
  model?: {
    model?: string | null
    provider?: string | null
  }
}

export function deriveSetupSnapshot(signals: SetupSignals): SetupSnapshot {
  return {
    model: signals.model?.provider && signals.model.model ? 'ready' : 'needs-setup',
    computer: !signals.computer
      ? 'unavailable'
      : signals.computer.ready
        ? 'ready'
        : signals.computer.platform_supported
          ? 'needs-setup'
          : 'unavailable',
    messaging: signals.messaging?.some(platform => platform.enabled && platform.state === 'connected')
      ? 'ready'
      : 'optional',
    memory: signals.memory?.active ? 'ready' : 'needs-setup'
  }
}

function Surface({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <section className={`mm-page-surface ${className}`}>{children}</section>
}

function SectionTitle({ children, detail }: { children: ReactNode; detail?: string }) {
  return (
    <div className="mm-section-title">
      <h2>{children}</h2>
      {detail ? <p>{detail}</p> : null}
    </div>
  )
}

function StatusBadge({ status }: { status: 'checking' | 'needs-setup' | 'optional' | 'ready' | 'unavailable' }) {
  const copy = {
    checking: 'Checking',
    'needs-setup': 'Needs setup',
    optional: 'Optional',
    ready: 'Ready',
    unavailable: 'Unavailable'
  }[status]

  return <span className={`mm-status-badge is-${status}`}>{copy}</span>
}

function SetupRow({
  description,
  icon: Icon,
  label,
  onClick,
  status
}: {
  description: string
  icon: typeof Zap
  label: string
  onClick: () => void
  status: 'checking' | 'needs-setup' | 'optional' | 'ready' | 'unavailable'
}) {
  return (
    <button className="mm-setup-row" onClick={onClick} type="button">
      <span className="mm-row-symbol">
        <Icon aria-hidden />
      </span>
      <span className="mm-row-copy">
        <strong>{label}</strong>
        <small>{description}</small>
      </span>
      <StatusBadge status={status} />
      <ChevronRight aria-hidden className="mm-row-chevron" />
    </button>
  )
}

function SetupPage({ onNavigate }: { onNavigate: (view: MacManView) => void }) {
  const gatewayState = useStore($gatewayState)
  const [snapshot, setSnapshot] = useState(INITIAL_SETUP)
  const generation = useRef(0)

  const refresh = useCallback(() => {
    const request = ++generation.current
    setSnapshot(INITIAL_SETUP)

    void Promise.allSettled([getGlobalModelInfo(), getComputerUseStatus(), getMessagingPlatforms(), getMemoryStatus()]).then(
      results => {
        if (request !== generation.current) {
          return
        }

        const [model, computer, messaging, memory] = results
        setSnapshot(
          deriveSetupSnapshot({
            computer: computer.status === 'fulfilled' ? computer.value : undefined,
            memory: memory.status === 'fulfilled' ? memory.value : undefined,
            messaging: messaging.status === 'fulfilled' ? messaging.value.platforms : undefined,
            model: model.status === 'fulfilled' ? model.value : undefined
          })
        )
      }
    )
  }, [])

  useEffect(() => {
    refresh()

    return () => void ++generation.current
  }, [refresh])

  return (
    <Surface>
      <div className="mm-page-heading">
        <div>
          <span className="mm-eyebrow">Get started</span>
          <h2>Make MacMan useful on this Mac</h2>
          <p>Finish only what you need. Chat keeps working while optional capabilities stay off.</p>
        </div>
        <Button onClick={refresh} size="sm" type="button" variant="outline">
          <RefreshCw />
          Recheck
        </Button>
      </div>

      <div className="mm-card-list">
        <SetupRow
          description="Connect at least one provider and choose the model used for new work."
          icon={Zap}
          label="AI model"
          onClick={() => onNavigate('models')}
          status={snapshot.model}
        />
        <SetupRow
          description="Accessibility and Screen Recording let MacMan see and operate your desktop."
          icon={Monitor}
          label="Computer control"
          onClick={() => onNavigate('permissions')}
          status={snapshot.computer}
        />
        <SetupRow
          description="The local gateway carries the continuous conversation and every Hermes action."
          icon={MessageCircle}
          label="Conversation"
          onClick={() => onNavigate('chat')}
          status={gatewayState === 'open' ? 'ready' : 'needs-setup'}
        />
        <SetupRow
          description="Connect any messaging adapter that you want MacMan to receive from."
          icon={Bell}
          label="Messaging"
          onClick={() => onNavigate('messaging')}
          status={snapshot.messaging}
        />
        <SetupRow
          description="Durable local memory can help future conversations without changing the runtime."
          icon={Brain}
          label="Memory"
          onClick={() => onNavigate('memory')}
          status={snapshot.memory}
        />
      </div>
    </Surface>
  )
}

function PermissionInfoRow({
  description,
  icon: Icon,
  label,
  status
}: {
  description: string
  icon: typeof Zap
  label: string
  status: string
}) {
  return (
    <div className="mm-permission-info-row">
      <span className="mm-row-symbol">
        <Icon aria-hidden />
      </span>
      <span className="mm-row-copy">
        <strong>{label}</strong>
        <small>{description}</small>
      </span>
      <span className="mm-permission-copy">{status}</span>
    </div>
  )
}

function PermissionsPage() {
  return (
    <Surface>
      <span className="mm-eyebrow">System access</span>
      <div className="mm-page-heading">
        <div>
          <h2>Permissions</h2>
          <p>macOS stays authoritative. MacMan reports what the process that actually performs the work can access.</p>
        </div>
      </div>

      <SectionTitle detail="Optional local activity history. The recorder is not bundled in this fresh build yet.">
        Continuous awareness
      </SectionTitle>
      <div className="mm-inset-card mm-stalker-card">
        <span className="mm-row-symbol">
          <Eye aria-hidden />
        </span>
        <span className="mm-row-copy">
          <strong>Stalker</strong>
          <small>When installed, this stays local and depends on Screen Recording permission.</small>
        </span>
        <StatusBadge status="unavailable" />
      </div>

      <SectionTitle detail="Both permissions are required for reliable computer control.">Computer control</SectionTitle>
      <div className="mm-inset-card mm-embedded-control">
        <ComputerUsePanel />
      </div>

      <SectionTitle detail="These are requested only when the feature is used.">Feature access</SectionTitle>
      <div className="mm-inset-card">
        <PermissionInfoRow
          description="Requested when you start voice input or a voice conversation."
          icon={Mic}
          label="Microphone"
          status="Asked when used"
        />
        <PermissionInfoRow
          description="Requested when you enable completion, failure, or approval alerts."
          icon={Bell}
          label="Notifications"
          status="Asked when enabled"
        />
        <PermissionInfoRow
          description="macOS asks separately the first time MacMan controls each Apple app."
          icon={Zap}
          label="App Automation"
          status="Per app"
        />
        <PermissionInfoRow
          description="Requested by macOS when a selected folder is outside the app's existing scope."
          icon={Lock}
          label="Files and folders"
          status="Asked when used"
        />
        <PermissionInfoRow
          description="Needed only for unrestricted local files or local Messages history."
          icon={ShieldLock}
          label="Full Disk Access"
          status="Optional"
        />
      </div>

      <SectionTitle detail="Visible by design, but not claimed as working until an integration is enabled.">
        Deferred integrations
      </SectionTitle>
      <div className="mm-inset-card">
        {DEFERRED_MACMAN_CAPABILITIES.map(item => (
          <PermissionInfoRow
            description={`${item.label} access will be requested in context when its product integration ships.`}
            icon={Info}
            key={item.id}
            label={item.label}
            status="Not enabled"
          />
        ))}
      </div>
    </Surface>
  )
}

function ConfigPage({
  section
}: {
  section: 'advanced' | 'browser' | 'chat' | 'memory' | 'model' | 'safety' | 'voice' | 'workspace'
}) {
  const importInputRef = useRef<HTMLInputElement>(null)

  return <ConfigSettings activeSectionId={section} importInputRef={importInputRef} />
}

function GeneralPage() {
  return <ConfigPage section="chat" />
}

function ModelsPage() {
  const [view, setView] = useState<'model' | ProviderView>('model')

  return (
    <div className="mm-settings-page">
      <div className="mm-segmented-wrap">
        <SegmentedControl
          aria-label="AI model settings"
          onChange={value => setView(value as 'model' | ProviderView)}
          options={[
            { id: 'model', label: 'Model' },
            { id: 'accounts', label: 'Accounts' },
            { id: 'keys', label: 'API Keys' },
            { id: 'custom-endpoints', label: 'Endpoints' }
          ]}
          value={view}
        />
      </div>
      {view === 'model' ? (
        <ConfigPage section="model" />
      ) : (
        <ProvidersSettings onClose={() => undefined} onViewChange={setView} view={view} />
      )}
    </div>
  )
}

function AboutPage() {
  const version = useStore($desktopVersion)

  useEffect(() => {
    void refreshDesktopVersion()
  }, [])

  return (
    <Surface className="mm-about-page">
      <img alt="MacMan" className="mm-about-mark" src="./macman-mark-transparent.png" />
      <h2>MacMan</h2>
      <p>Personal assistant for this Mac.</p>
      <div className="mm-about-grid">
        <span>App version</span>
        <strong>{version?.appVersion ?? 'Checking…'}</strong>
        <span>Runtime</span>
        <strong>Built-in agent runtime</strong>
        <span>Conversation</span>
        <strong>Continuous, local desktop session</strong>
      </div>
      <p className="mm-about-note">
        Runtime names are intentionally technical detail. MacMan is the product identity shown throughout the app.
      </p>
    </Surface>
  )
}

function UnsupportedView({ view }: { view: never }) {
  return (
    <Surface>
      <AlertTriangle /> Unknown view: {String(view)}
    </Surface>
  )
}

export function MacManPages({ onNavigate, view }: MacManPagesProps) {
  switch (view) {
    case 'setup':
      return <SetupPage onNavigate={onNavigate} />
    case 'permissions':
      return <PermissionsPage />
    case 'general':
      return <GeneralPage />
    case 'models':
      return <ModelsPage />
    case 'messaging':
      return <MessagingView />
    case 'voice':
      return <ConfigPage section="voice" />
    case 'notifications':
      return <NotificationsSettings />
    case 'browser':
      return <ConfigPage section="browser" />
    case 'memory':
      return <ConfigPage section="memory" />
    case 'privacy':
      return <ConfigPage section="safety" />
    case 'workspace':
      return <ConfigPage section="workspace" />
    case 'capabilities':
      return <SkillsView embedded />
    case 'advanced':
      return <ConfigPage section="advanced" />
    case 'about':
      return <AboutPage />
    default:
      return <UnsupportedView view={view} />
  }
}
