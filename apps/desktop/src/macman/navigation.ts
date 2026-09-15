import type { IconComponent } from '@/lib/icons'
import {
  Bell,
  Box,
  Brain,
  FolderOpen,
  Globe,
  HelpCircle,
  Info,
  Lock,
  MessageCircle,
  MessageSquareText,
  Mic,
  Package,
  Settings,
  ShieldLock,
  Wrench,
  Zap
} from '@/lib/icons'

export type MacManView =
  | 'chat'
  | 'setup'
  | 'permissions'
  | 'general'
  | 'models'
  | 'messaging'
  | 'voice'
  | 'notifications'
  | 'browser'
  | 'memory'
  | 'privacy'
  | 'workspace'
  | 'capabilities'
  | 'advanced'
  | 'about'

export interface MacManNavigationItem {
  description: string
  icon: IconComponent
  id: MacManView
  label: string
}

export interface MacManNavigationGroup {
  id: 'primary' | 'settings'
  items: readonly MacManNavigationItem[]
  label?: string
}

export const MACMAN_NAVIGATION: readonly MacManNavigationGroup[] = [
  {
    id: 'primary',
    items: [
      {
        id: 'chat',
        label: 'Chat',
        description: 'One continuous conversation with MacMan.',
        icon: MessageCircle
      },
      {
        id: 'setup',
        label: 'Setup',
        description: 'Finish the small number of steps needed to get useful work done.',
        icon: Zap
      },
      {
        id: 'permissions',
        label: 'Permissions',
        description: 'See exactly what this Mac has granted and why it is needed.',
        icon: ShieldLock
      }
    ]
  },
  {
    id: 'settings',
    label: 'Settings',
    items: [
      {
        id: 'general',
        label: 'General',
        description: 'Appearance, language, launch behavior, and chat defaults.',
        icon: Settings
      },
      {
        id: 'models',
        label: 'AI Models',
        description: 'Connect model accounts and choose the model MacMan uses.',
        icon: Box
      },
      {
        id: 'messaging',
        label: 'Messaging',
        description: 'Connect and manage the messaging adapters available in the runtime.',
        icon: MessageSquareText
      },
      {
        id: 'voice',
        label: 'Voice & Audio',
        description: 'Choose listening, transcription, speaking, and voice behavior.',
        icon: Mic
      },
      {
        id: 'notifications',
        label: 'Notifications',
        description: 'Choose which important events can reach you outside the app.',
        icon: Bell
      },
      {
        id: 'browser',
        label: 'Browser',
        description: 'Control managed browsing, profile access, and secure credential fill.',
        icon: Globe
      },
      {
        id: 'memory',
        label: 'Memory & Context',
        description: 'Control durable memory, profile learning, and conversation compression.',
        icon: Brain
      },
      {
        id: 'privacy',
        label: 'Privacy & Safety',
        description: 'Approvals, secret handling, checkpoints, exclusions, and data controls.',
        icon: Lock
      },
      {
        id: 'workspace',
        label: 'Workspace',
        description: 'Choose where local work runs and what repositories are visible.',
        icon: FolderOpen
      },
      {
        id: 'capabilities',
        label: 'Capabilities',
        description: 'Manage toolsets, skills, plugins, MCP servers, and computer use.',
        icon: Package
      },
      {
        id: 'advanced',
        label: 'Advanced',
        description: 'Tune execution, delegation, limits, diagnostics, and runtime behavior.',
        icon: Wrench
      },
      {
        id: 'about',
        label: 'About',
        description: 'Version, updates, licenses, privacy, and diagnostic information.',
        icon: Info
      }
    ]
  }
] as const

export const MACMAN_VIEWS = MACMAN_NAVIGATION.flatMap(group => group.items.map(item => item.id))

export function macManNavigationItem(view: MacManView): MacManNavigationItem {
  const item = MACMAN_NAVIGATION.flatMap(group => group.items).find(candidate => candidate.id === view)

  if (!item) {
    throw new Error(`Unknown MacMan view: ${view}`)
  }

  return item
}

export const DEFERRED_MACMAN_CAPABILITIES = [
  { id: 'contacts', label: 'Contacts' },
  { id: 'calendar', label: 'Calendar' },
  { id: 'reminders', label: 'Reminders' }
] as const

export const MACMAN_REQUIREMENTS_HELP = HelpCircle
