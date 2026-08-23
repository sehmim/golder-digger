import { useRef, useState } from 'react'
import { useApplication } from '../../application/ApplicationState'
import InterfaceMenu from '../../shared/components/InterfaceMenu'
import type { InterfaceId } from '../../shared/interfaceNavigation'
import FolderStrip from './FolderStrip'
import GoldenKnob from './GoldenKnob'
import GoldenResults from './GoldenResults'
import type { GoldenResultsState } from './GoldenResults'
import IngestStrip from './IngestStrip'
import SettingsOverlay from './SettingsOverlay'

const RESULT_COUNT = 30

interface GoldenAppProps {
  onNavigate: (destination: InterfaceId) => void
  onOpenFolderManager: (folderId?: string) => void
}

function tonalCenter(key: string | null): string | null {
  return key?.match(/^[A-G](?:#|b)?/)?.[0] ?? null
}

export default function GoldenApp({
  onNavigate,
  onOpenFolderManager
}: GoldenAppProps): React.JSX.Element {
  const { state, actions } = useApplication()
  const [value, setValue] = useState(50)
  const [results, setResults] = useState<GoldenResultsState>({ status: 'idle' })
  const [contextLoading, setContextLoading] = useState(false)
  const [contextError, setContextError] = useState<string | null>(null)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const requestGeneration = useRef(0)
  const tempo = state.project?.session.tempo ?? null
  const center = tonalCenter(state.project?.session.key ?? null)
  const hasUsableContext = Boolean(state.project && state.project.context_ids.length > 0)
  const contextSummary = [tempo === null ? null : `${Math.round(tempo)} BPM`, center]
    .filter(Boolean)
    .join(' · ')

  async function chooseContext(): Promise<void> {
    const path = await window.desktop.selectProject()
    if (!path) return

    setContextLoading(true)
    setContextError(null)
    try {
      actions.setProject(await window.desktop.loadSet(path))
    } catch (cause) {
      setContextError(cause instanceof Error ? cause.message : String(cause))
    } finally {
      setContextLoading(false)
    }
  }

  function rank(distance: number): void {
    const project = state.project
    if (!project) {
      void chooseContext()
      return
    }

    if (project.context_ids.length === 0) {
      setResults({
        status: 'error',
        distance,
        message: 'This project has no resolved audio to use as context.'
      })
      return
    }

    const generation = ++requestGeneration.current
    setResults({ status: 'loading', distance })
    void window.desktop
      .analyze(
        project.context_ids,
        distance,
        RESULT_COUNT,
        project.session.path,
        state.activeFolderRoots
      )
      .then((result) => {
        if (requestGeneration.current === generation) {
          setResults({ status: 'ready', distance, result })
        }
      })
      .catch((cause) => {
        if (requestGeneration.current === generation) {
          setResults({
            status: 'error',
            distance,
            message: cause instanceof Error ? cause.message : String(cause)
          })
        }
      })
  }

  function returnToKnob(): void {
    requestGeneration.current += 1
    setResults({ status: 'idle' })
  }

  return (
    <main className="golden-page" aria-label="Golden UI">
      <button
        type="button"
        className="golden-context-trigger"
        data-error={contextError || undefined}
        onClick={() => void chooseContext()}
        title={contextError ?? state.project?.session.path}
        disabled={contextLoading}
      >
        {state.project ? (
          <>
            <span className="golden-context-trigger__name">{state.project.session.name}</span>
            <span className="golden-context-trigger__meta">
              {contextLoading ? 'Reading…' : (contextError ?? contextSummary) || 'Context'}
            </span>
          </>
        ) : (
          <>
            <span className="golden-context-trigger__name">No Ableton project</span>
            <span className="golden-context-trigger__meta">
              {contextLoading ? 'Reading…' : contextError ?? '+ Choose .als'}
            </span>
          </>
        )}
      </button>
      <div className="golden-page__controls">
        <FolderStrip folders={state.folders} onOpenManager={onOpenFolderManager} />
        <button
          type="button"
          className="golden-settings-trigger"
          aria-label="Open settings"
          title="Settings"
          onClick={() => setSettingsOpen(true)}
        >
          ◎
        </button>
        <InterfaceMenu current="golden" onNavigate={onNavigate} />
      </div>
      <GoldenKnob
        value={value}
        onChange={setValue}
        onCommit={rank}
        style={state.settings.knobStyle}
        disabled={!hasUsableContext || contextLoading}
      />
      <IngestStrip />
      {results.status !== 'idle' ? <GoldenResults state={results} onBack={returnToKnob} /> : null}
      {settingsOpen ? <SettingsOverlay onClose={() => setSettingsOpen(false)} /> : null}
    </main>
  )
}
