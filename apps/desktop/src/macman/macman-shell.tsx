import { useStore } from '@nanostores/react'
import { type ReactNode, useEffect, useMemo, useState } from 'react'

import { cn } from '@/lib/utils'
import { $gatewayState } from '@/store/session'

import { ContribWiring, WiredPane } from '../app/contrib/wiring'

import { MacManPages } from './macman-pages'
import { MACMAN_NAVIGATION, macManNavigationItem, type MacManView } from './navigation'

interface MacManShellProps {
  detail?: (view: Exclude<MacManView, 'chat'>, navigate: (view: MacManView) => void) => ReactNode
  initialView?: MacManView
}

function ConnectionState() {
  const gatewayState = useStore($gatewayState)
  const open = gatewayState === 'open'
  const label = open ? 'Ready' : gatewayState === 'connecting' ? 'Connecting' : 'Offline'

  return (
    <span className="mm-connection" data-state={open ? 'ready' : gatewayState}>
      <span aria-hidden className="mm-connection-dot" />
      {label}
    </span>
  )
}

function MacManSidebar({ active, onSelect }: { active: MacManView; onSelect: (view: MacManView) => void }) {
  return (
    <aside aria-label="MacMan" className="mm-sidebar">
      <div aria-hidden className="mm-window-drag" />
      <div className="mm-brand">
        <img alt="" className="mm-brand-mark" src="./macman-mark-transparent.png" />
        <span>
          <strong>MacMan</strong>
          <small>Personal assistant</small>
        </span>
      </div>

      <nav aria-label="MacMan navigation" className="mm-navigation">
        {MACMAN_NAVIGATION.map(group => (
          <div className="mm-navigation-group" key={group.id}>
            {group.label ? <p>{group.label}</p> : null}
            {group.items.map(item => {
              const Icon = item.icon

              return (
                <button
                  aria-current={active === item.id ? 'page' : undefined}
                  className={cn('mm-navigation-item', active === item.id && 'is-active')}
                  key={item.id}
                  onClick={() => onSelect(item.id)}
                  type="button"
                >
                  <Icon aria-hidden className="mm-navigation-icon" />
                  <span>{item.label}</span>
                </button>
              )
            })}
          </div>
        ))}
      </nav>

      <div className="mm-sidebar-footer">
        <ConnectionState />
      </div>
    </aside>
  )
}

function PlaceholderDetail({ view }: { view: Exclude<MacManView, 'chat'> }) {
  const item = useMemo(() => macManNavigationItem(view), [view])
  const Icon = item.icon

  return (
    <section className="mm-placeholder">
      <span className="mm-placeholder-icon">
        <Icon aria-hidden />
      </span>
      <h2>{item.label}</h2>
      <p>{item.description}</p>
      <span className="mm-placeholder-status">Connecting this screen to MacMan…</span>
    </section>
  )
}

function MacManShell({ detail, initialView = 'chat' }: MacManShellProps) {
  const [activeView, setActiveView] = useState<MacManView>(initialView)
  const page = macManNavigationItem(activeView)

  return (
    <main className="mm-app">
      <MacManSidebar active={activeView} onSelect={setActiveView} />
      <section className="mm-detail">
        <header className="mm-detail-header">
          <div>
            <h1>{activeView === 'chat' ? 'MacMan' : page.label}</h1>
            <p>{activeView === 'chat' ? 'One continuous conversation on this Mac.' : page.description}</p>
          </div>
          <ConnectionState />
        </header>

        <div className="mm-detail-body">
          <div aria-hidden={activeView !== 'chat'} className={cn('mm-chat-host', activeView !== 'chat' && 'is-hidden')}>
            <WiredPane part="chatRoutes" />
          </div>
          {activeView !== 'chat' ? (
            <div className="mm-settings-host">
              {detail?.(activeView, setActiveView) ?? <PlaceholderDetail view={activeView} />}
            </div>
          ) : null}
        </div>
      </section>
    </main>
  )
}

export function MacManController() {
  useEffect(() => {
    document.title = 'MacMan'
  }, [])

  return (
    <ContribWiring presentation="macman">
      <MacManShell detail={(view, navigate) => <MacManPages onNavigate={navigate} view={view} />} />
    </ContribWiring>
  )
}

export { MacManShell }
