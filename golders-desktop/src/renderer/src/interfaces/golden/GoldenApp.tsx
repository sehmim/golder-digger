import { useState } from 'react'
import { useApplication } from '../../application/ApplicationState'
import InterfaceMenu from '../../shared/components/InterfaceMenu'
import type { InterfaceId } from '../../shared/interfaceNavigation'
import FolderStrip from './FolderStrip'
import GoldenKnob from './GoldenKnob'

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
  const tempo = state.project?.session.tempo ?? null
  const center = tonalCenter(state.project?.session.key ?? null)
  const contextSummary = [tempo === null ? null : `${Math.round(tempo)} BPM`, center]
    .filter(Boolean)
    .join(' · ')

  return (
    <main className="golden-page" aria-label="Golden UI">
      <button
        type="button"
        className="golden-context-trigger"
        onClick={onOpenContextSelector}
        title={state.project?.session.name}
      >
        {state.project ? contextSummary || 'Context' : 'Select context'}
      </button>
      <div className="golden-page__controls">
        <FolderStrip folders={state.folders} onOpenManager={onOpenFolderManager} />
        <InterfaceMenu current="golden" onNavigate={onNavigate} />
      </div>
      <GoldenKnob value={value} onChange={setValue} style={state.settings.knobStyle} />
    </main>
  )
}
