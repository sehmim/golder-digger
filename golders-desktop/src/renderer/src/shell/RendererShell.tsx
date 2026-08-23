import { useCallback, useEffect, useState } from 'react'
import DevApp from '../interfaces/dev/DevApp'
import GoldDiggerApp from '../interfaces/gold-digger/GoldDiggerApp'
import type { GoldDiggerDiagnostics } from '../interfaces/gold-digger/types'
import GoldenApp from '../interfaces/golden/GoldenApp'
import SettingsApp from '../interfaces/settings/SettingsApp'
import type { InterfaceId } from '../shared/interfaceNavigation'

const INITIAL_GOLD_DIGGER_DIAGNOSTICS: GoldDiggerDiagnostics = {
  currentStep: 'sources',
  leavingStep: null,
  visiblePanels: ['sources'],
  hasReachedProject: false
}

export default function RendererShell(): React.JSX.Element {
  const [activeInterface, setActiveInterface] = useState<InterfaceId>('gold-digger')
  const [goldDiggerDiagnostics, setGoldDiggerDiagnostics] = useState(INITIAL_GOLD_DIGGER_DIAGNOSTICS)
  const updateGoldDiggerDiagnostics = useCallback(
    (diagnostics: GoldDiggerDiagnostics) => setGoldDiggerDiagnostics(diagnostics),
    []
  )

  useEffect(() => {
    if (!window.desktop.onDevPageToggle) return
    return window.desktop.onDevPageToggle(() => setActiveInterface('dev'))
  }, [])

  useEffect(() => {
    if (!window.desktop.onSettingsPageOpen) return
    return window.desktop.onSettingsPageOpen(() => setActiveInterface('settings'))
  }, [])

  // Renderer fallback: main/preload changes require an Electron restart, while
  // renderer code hot-reloads. Keeping the same shortcuts here makes newly
  // added interfaces reachable immediately during development.
  useEffect(() => {
    const openInterface = (event: KeyboardEvent): void => {
      const isInterfaceShortcut =
        event.metaKey && event.altKey && !event.ctrlKey && !event.shiftKey && !event.repeat
      if (!isInterfaceShortcut) return

      if (event.code === 'KeyD') {
        event.preventDefault()
        setActiveInterface('dev')
      }

      if (event.code === 'KeyS') {
        event.preventDefault()
        setActiveInterface('settings')
      }
    }

    window.addEventListener('keydown', openInterface)
    return () => window.removeEventListener('keydown', openInterface)
  }, [])

  return (
    <div className="renderer-shell">
      <div className="interface-view" hidden={activeInterface !== 'gold-digger'}>
        <GoldDiggerApp onDiagnosticsChange={updateGoldDiggerDiagnostics} />
      </div>
      <div className="interface-view" hidden={activeInterface !== 'dev'}>
        <DevApp
          goldDigger={goldDiggerDiagnostics}
          onNavigate={setActiveInterface}
        />
      </div>
      <div className="interface-view" hidden={activeInterface !== 'golden'}>
        <GoldenApp onNavigate={setActiveInterface} />
      </div>
      <div className="interface-view" hidden={activeInterface !== 'settings'}>
        <SettingsApp onNavigate={setActiveInterface} />
      </div>
    </div>
  )
}
