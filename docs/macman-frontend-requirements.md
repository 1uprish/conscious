# MacMan frontend requirements

Status: approved implementation contract  
Product: MacMan desktop for macOS  
Runtime: Hermes, behind the MacMan conversational adapter

This document is the required inventory gate for the MacMan frontend. A surface is not complete
because it renders: every operational control must read from and write to the authority named below.
The frontend must never duplicate Hermes behavior or present a renderer-only preference as a live
runtime setting.

## Product structure

MacMan is one persistent conversation with a compact settings surface. The primary window has:

1. A macOS sidebar with **Chat**, **Setup**, and **Permissions** at the top.
2. A Settings group containing **General**, **AI Models**, **Messaging**, **Voice & Audio**,
   **Notifications**, **Browser**, **Memory & Context**, **Privacy & Safety**, **Workspace**,
   **Capabilities**, **Advanced**, and **About**.
3. A single detail area. Navigation changes the detail area without remounting the shell or losing
   the chat draft.
4. A persistent connection indicator in the sidebar footer.

The conversation is the product. Settings exist to make the conversation capable and trustworthy;
they must not turn the app into a developer dashboard.

## Authority model

| State | Authority | Frontend behavior |
| --- | --- | --- |
| Conversation, streaming, approvals, tools, model work | Hermes gateway | Subscribe and reconcile; never synthesize completion. |
| Models, providers, memory, safety, browser, workspace, tools | Hermes config/API | Pull current values, save authoritatively, refresh after writes. |
| Accessibility, Screen Recording, microphone, notifications, Apple-app access | Electron + macOS | Show the effective OS state; request access only in context. |
| Messaging adapter health and pairing | Hermes messaging gateway | Render the dynamic platform catalog and real connection state. |
| Stalker capture health and storage | Stalker service | Show actual runtime state, permission dependency, pause/resume/open actions. |
| Appearance, reduced effects, sidebar presentation | Renderer | Apply immediately and persist per installation. |

All asynchronous requests need a generation or request token so a stale response cannot overwrite a
newer selection. Failed authoritative writes roll back visibly. Loading, empty, reconnecting, stale,
and failed states are distinct.

## Chat

### Components

- **Conversation header**: MacMan identity, one-line purpose, honest Ready/Connecting/Offline state,
  and Stop while the current Hermes turn is interruptible.
- **Transcript**: one continuous chronological conversation; user and MacMan messages; markdown,
  code, links, images, files, and tool-result attachments; virtualized for long history.
- **Immediate receipt**: every explicit delegated command receives an accepted acknowledgement as
  soon as the conversational layer admits it. This is not a completion claim.
- **Live activity**: one restrained inline row for thinking/tool activity. Detailed tool traces are
  hidden unless Developer Mode is enabled.
- **Approval card**: exact proposed action, risk/context, Allow and Deny. It resolves the existing
  Hermes approval; it never creates a second approval system.
- **Clarification card**: one focused question with reply input and optional choices. The answer
  resumes the same Hermes worker.
- **Draft/action card**: for messages, posts, or other reviewable external actions; shows recipient,
  channel, content, Edit, Send, and Cancel when Hermes requests review.
- **Composer**: multiline input, send/stop, file attachment picker/drop/paste, model picker, voice
  input, and keyboard help. Sending remains available while background work runs.
- **Recovery banner**: actionable model/auth/network/runtime errors with Retry or Open Settings.
- **Conversation bootstrap**: bounded connection ladder with retry; never an infinite spinner.

### Behavior

- Ordinary chat enters the MacMan conversation adapter; Hermes remains the only executor.
- Greetings and casual conversation remain in the fast layer. Work is acknowledged and delegated
  with the user's exact content and attachments.
- Worker results re-enter the conversational layer for concise delivery. Permissions,
  clarifications, failures, and uncertainty must remain semantically intact.
- A user follow-up may resume only an owned, completed worker inside its follow-up window.
- User messages have delivery states: Sending, Accepted, Failed. Assistant claims use evidence from
  Hermes; the UI must never label an external action complete from model prose alone.
- Escape stops one current action. Command-Return sends; Shift-Return inserts a line break.

## Setup

Setup is a resumable checklist, not a blocking wizard:

1. **AI ready**: at least one usable model account or local model.
2. **Computer control ready**: Accessibility and Screen Recording granted.
3. **Conversation ready**: gateway connected and persistent chat opened.
4. **Optional capabilities**: messaging, voice, notifications, Stalker, memory.

Each row shows why it is needed, current truth, one primary action, and a route to its full settings
page. Chat remains available without computer-control permissions; the UI labels that reduced
capability honestly.

## Permissions

### Required for computer control

- **Accessibility**: click, type, inspect accessibility trees, and use shortcuts.
- **Screen & System Audio Recording**: see screen content and, where supported, system audio.

### Requested when used

- **Microphone**: voice input/conversation.
- **Notifications**: task completion, failure, and approval alerts.
- **Automation**: per-app Apple Events access.
- **Files and folders**: scoped filesystem access where macOS requires it.

### Optional capability access

- **Full Disk Access**: local Messages history and explicitly unrestricted local workflows.
- **Location**: local weather, travel, and nearby answers.
- **Contacts**, **Calendar**, and **Reminders**: visible but deferred until those product integrations
  are enabled; do not claim support from permission state alone.

### Stalker

Stalker lives at the top of Permissions under Continuous awareness. It shows Off, Recording,
Paused, Needs Screen Recording, Starting, or Failed; local archive size; Enable/Pause/Resume;
Capture now; Open timeline; retry; and the exact macOS Settings route when blocked. It uses MacMan
branding and opens natively inside the app rather than a localhost browser URL.

## General

- Launch at login.
- Menu-bar availability and global shortcut.
- Close behavior: keep running or quit.
- Appearance: System, Light, Dark.
- Reduced transparency and reduced motion follow macOS by default, with an optional stricter override.
- Language.
- Automatic updates, update channel, current version, Check for Updates.

Machine lifecycle settings are owned by Electron. Appearance is renderer-owned. Update state comes
from the updater and must distinguish checking, available, downloading, ready, and failed.

## AI Models

- **Accounts**: dynamic provider catalog with OAuth/account connection where supported.
- **API keys**: Keychain-backed credential rows; masked by default; reveal requires explicit action.
- **Custom endpoints**: name, base URL, protocol/provider compatibility, key reference, test result.
- **Local models**: visible only when the runtime supports them; discovery, start/stop, health.
- **Default model**: current provider/model used for new work.
- **Fallback models**: ordered provider:model list.
- **Context window** and **service tier** when supported.
- **Delegated worker model**, reasoning effort, concurrency, timeout, and turn limit under Advanced.

The catalog is backend-driven—never a hardcoded provider snapshot. Saving a model selection updates
Hermes and the chat composer together. Connection tests must exercise the same auth/model request
path used by chat.

## Messaging

- Dynamic adapter list from Hermes, including iMessage/BlueBubbles or Photon, WhatsApp, Telegram,
  Slack, Discord, Signal, and future adapters when installed.
- Per-adapter state: Disabled, Needs setup, Connecting, Connected, Degraded, Failed.
- Credential or QR/pairing setup appropriate to the adapter.
- Approved-user allowlist, pending pairing requests, approve/revoke.
- Inbound/outbound capability summary, attachment support, and last successful health event.
- Save, Disable, Reconnect, and Restart gateway when required.

The UI must not claim Connected from saved credentials alone. It displays gateway-observed health.
Connector secrets remain backend/Keychain owned. Adapter-specific advanced fields live behind a
disclosure, while the common path is one Connect action.

## Voice & Audio

- Voice mode: chained speech-to-text → Hermes → speech, or supported live voice mode.
- Microphone and speaker selection.
- Push-to-talk/global recording shortcut.
- Speech-to-text provider, model, language, transcript echo, recording limit.
- Text-to-speech provider, model, voice, speed, and preview.
- Auto-speak responses and allow interruption.
- Input level, listening, transcribing, speaking, muted, and error states.

Voice must delegate real work to the same Hermes conversation and preserve the same approval cards.

## Notifications

- Notify when work completes, fails, or needs approval.
- Sound toggle and restrained sound selection.
- Respect macOS Focus.
- Background notification behavior and in-app banner behavior.
- A test-notification action that verifies the actual OS path.

## Browser

- Managed browser availability and health.
- Use a refreshed copy of the signed-in Chromium profile, with explicit consent.
- Allow private URLs and automatically use local browsing for private URLs.
- Browser profile refresh/disconnect and clear explanation that the live profile is not driven.
- Credential Vault: origin-bound saved credentials used through the existing secure fill path.

## Memory & Context

- Persistent memory on/off.
- User profile on/off.
- Local storage status and storage location disclosure.
- Memory provider discovery/configuration; no requirement for a second model key when the selected
  Hermes model performs extraction.
- Memory and profile budgets.
- Context engine.
- Auto-compression, threshold, target ratio, and protected recent messages.
- Inspect memories/profile, delete an individual memory, reset memory/profile/all, export.

Memory writes affect future turns and must say so. Destructive reset actions require confirmation.

## Privacy & Safety

- Approval mode and timeout.
- Command allowlist.
- Secret redaction.
- Private-URL policy.
- File checkpoints and rollback availability.
- Excluded applications, windows, and folders for Stalker/computer use.
- Sensitive-field and private/incognito capture exclusions.
- Local diagnostic/log retention and optional crash reporting.
- Data export and reset with an exact description of what is and is not removed.

## Workspace

- Default working folder.
- Repository scanning, roots, and excluded paths.
- Code-execution scope.
- Persistent shell.
- Environment-variable passthrough with secret warning.
- File-read limit.
- Current local/remote runtime target, where supported.

## Capabilities

- Enabled Hermes toolsets.
- Installed skills and plugins, with enable/disable and restart/deferred-activation status.
- MCP servers, connection health, tool count, reconnect, and removal.
- Computer-use runtime health and version.

Capability changes follow Hermes prompt-cache rules: changes are deferred to the next conversation
unless the backend offers an explicit immediate invalidation action.

## Advanced

- Terminal backend and backend-specific images/connection fields.
- Terminal and tool-output limits.
- Agent turns, retries, enforcement mode, and service tier.
- Delegation model/provider, reasoning effort, concurrency, timeout, and turn limit.
- Checkpoint retention.
- Runtime health, gateway restart, redacted logs, and Developer Mode.
- Import/export configuration and Reset to Defaults.

Advanced is one level deeper and searchable. It must not be required for ordinary setup.

## About

- MacMan name, icon, version, build, update channel, licenses, privacy policy, and support links.
- Runtime version and diagnostic-copy action, labeled as technical detail rather than Hermes branding.

## Apple design system application

- Use the macOS system font, optical sizing, compact title hierarchy, and semantic system colors.
- Sidebar uses a heavier translucent material; content and floating composer use lighter materials
  without stacking translucent layers.
- 8-point spacing grid; 44-point minimum primary hit targets and at least 28 points for compact
  desktop controls with expanded pointer hit areas.
- Controls use familiar macOS shapes: sidebar rows, inset grouped lists, switches, popovers, sheets,
  segmented controls, disclosure groups, and destructive confirmation dialogs.
- Press feedback starts immediately. Navigation and sheets use critically damped, interruptible
  motion. No decorative bounce.
- Respect reduced motion, reduced transparency, increased contrast, keyboard navigation, VoiceOver,
  Dynamic Type/zoom, and visible focus rings.
- Status always combines color with text/icon. Errors appear near the responsible control and offer
  recovery; success does not steal focus.
- The common path is visible; provider-specific and runtime detail is progressively disclosed.

## Required validation

- Unit tests for navigation, settings authority, stale-response protection, rollback, and permission
  state mapping.
- Contract tests for gateway methods used by chat, models, messaging, memory, and approvals.
- Desktop tests for keyboard navigation, reduced effects, long transcript performance, reconnect,
  provider failure, denied permission, and unavailable capability.
- Packaged macOS smoke test proving the signed app identity receives the permissions shown.
- Real model chat, real approval/clarification, one real computer action, and one real connector
  round trip before claiming end-to-end completion.

