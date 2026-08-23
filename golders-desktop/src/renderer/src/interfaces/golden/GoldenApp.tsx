import { useState } from 'react'
import { useApplication } from '../../application/ApplicationState'
import InterfaceMenu from '../../shared/components/InterfaceMenu'
import type { InterfaceId } from '../../shared/interfaceNavigation'
import GoldenKnob from './GoldenKnob'

interface GoldenAppProps {
  onNavigate: (destination: InterfaceId) => void
}

export default function GoldenApp({ onNavigate }: GoldenAppProps): React.JSX.Element {
  const { state } = useApplication()
  const [value, setValue] = useState(50)

  return (
    <main className="golden-page" aria-label="Golden UI">
      <InterfaceMenu current="golden" onNavigate={onNavigate} />
      <GoldenKnob value={value} onChange={setValue} style={state.settings.knobStyle} />
    </main>
  )
}
