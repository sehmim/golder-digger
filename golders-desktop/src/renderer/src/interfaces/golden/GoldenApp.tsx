import { useState } from 'react'
import { useApplication } from '../../application/ApplicationState'
import InterfaceMenu from '../../shared/components/InterfaceMenu'
import type { InterfaceId } from '../../shared/interfaceNavigation'
import FolderStrip from './FolderStrip'
import GoldenKnob from './GoldenKnob'

interface GoldenAppProps {
  onNavigate: (destination: InterfaceId) => void
  onOpenFolderManager: (folderId?: string) => void
}

export default function GoldenApp({
  onNavigate,
  onOpenFolderManager
}: GoldenAppProps): React.JSX.Element {
  const { state } = useApplication()
  const [value, setValue] = useState(50)

  return (
    <main className="golden-page" aria-label="Golden UI">
      <div className="golden-page__controls">
        <FolderStrip folders={state.folders} onOpenManager={onOpenFolderManager} />
        <InterfaceMenu current="golden" onNavigate={onNavigate} />
      </div>
      <GoldenKnob value={value} onChange={setValue} style={state.settings.knobStyle} />
    </main>
  )
}
