import { useCallback, useEffect, useState } from 'react'
import { useApplication } from '../application/ApplicationState'
import GoldDiggerApp from '../interfaces/gold-digger/GoldDiggerApp'
import type { GoldDiggerDiagnostics } from '../interfaces/gold-digger/types'
import GoldenApp from '../interfaces/golden/GoldenApp'
import SettingsApp from '../interfaces/settings/SettingsApp'
import type { InterfaceId } from '../shared/interfaceNavigation'
import FolderManager from './FolderManager'

const INITIAL_GOLD_DIGGER_DIAGNOSTICS: GoldDiggerDiagnostics = {
  currentStep: 'sources',
  leavingStep: null,
  visiblePanels: ['sources'],
  hasReachedProject: false
}

export default function RendererShell(): React.JSX.Element {
  const { state } = useApplication()
  const [activeInterface, setActiveInterface] = useState<Exclude<InterfaceId, 'dev'>>('gold-digger')
  const [folderManager, setFolderManager] = useState<{
    open: boolean
    focusedFolderId: string | null
  }>({ open: false, focusedFolderId: null })
  const [goldDiggerDiagnostics, setGoldDiggerDiagnostics] = useState(INITIAL_GOLD_DIGGER_DIAGNOSTICS)
  const updateGoldDiggerDiagnostics = useCallback(
    (diagnostics: GoldDiggerDiagnostics) => setGoldDiggerDiagnostics(diagnostics),
    []
  )

  const navigate = useCallback((destination: InterfaceId): void => {
    if (destination === 'dev') {
      void window.desktop.openDevWindow()
      return
    }
    setActiveInterface(destination)
  }, [])

  useEffect(() => {
    window.desktop.publishDevSnapshot({
      application: state,
      interfaces: { goldDigger: goldDiggerDiagnostics }
    })
  }, [goldDiggerDiagnostics, state])

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
        void window.desktop.openDevWindow()
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
      <div className="interface-view" hidden={activeInterface !== 'golden'}>
        <GoldenApp
          onNavigate={navigate}
          onOpenFolderManager={(folderId) =>
            setFolderManager({ open: true, focusedFolderId: folderId ?? null })
          }
        />
      </div>
      <div className="interface-view" hidden={activeInterface !== 'settings'}>
        <SettingsApp onNavigate={navigate} />
      </div>
      {folderManager.open ? (
        <FolderManager
          focusedFolderId={folderManager.focusedFolderId}
          onClose={() => setFolderManager({ open: false, focusedFolderId: null })}
        />
      ) : null}
    </div>
  )
}
