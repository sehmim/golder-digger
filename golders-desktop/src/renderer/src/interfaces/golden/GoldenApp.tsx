import { useRef, useState } from 'react'
import { useApplication } from '../../application/ApplicationState'
import InterfaceMenu from '../../shared/components/InterfaceMenu'
import type { InterfaceId } from '../../shared/interfaceNavigation'
import FolderStrip from './FolderStrip'
import GoldenKnob from './GoldenKnob'
import GoldenResults from './GoldenResults'
import type { GoldenResultsState } from './GoldenResults'

const RESULT_COUNT = 30

interface GoldenAppProps {
  onNavigate: (destination: InterfaceId) => void
  onOpenFolderManager: (folderId?: string) => void
  onOpenContextSelector: () => void
}

function tonalCenter(key: string | null): string | null {
  return key?.match(/^[A-G](?:#|b)?/)?.[0] ?? null
}

export default function GoldenApp({
  onNavigate,
  onOpenFolderManager,
  onOpenContextSelector
}: GoldenAppProps): React.JSX.Element {
  const { state } = useApplication()
  const [value, setValue] = useState(50)
  const [results, setResults] = useState<GoldenResultsState>({ status: 'idle' })
  const requestGeneration = useRef(0)
  const tempo = state.project?.session.tempo ?? null
  const center = tonalCenter(state.project?.session.key ?? null)
  const contextSummary = [tempo === null ? null : `${Math.round(tempo)} BPM`, center]
    .filter(Boolean)
    .join(' · ')

  function rank(distance: number): void {
    const project = state.project
    if (!project) {
      onOpenContextSelector()
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
        onClick={onOpenContextSelector}
        title={state.project?.session.path}
      >
        {state.project ? (
          <>
            <span className="golden-context-trigger__name">{state.project.session.name}</span>
            <span className="golden-context-trigger__meta">{contextSummary || 'Context'}</span>
          </>
        ) : 'Select context'}
      </button>
      <div className="golden-page__controls">
        <FolderStrip folders={state.folders} onOpenManager={onOpenFolderManager} />
        <InterfaceMenu current="golden" onNavigate={onNavigate} />
      </div>
      <GoldenKnob
        value={value}
        onChange={setValue}
        onCommit={rank}
        style={state.settings.knobStyle}
      />
      {results.status !== 'idle' ? <GoldenResults state={results} onBack={returnToKnob} /> : null}
    </main>
  )
}
