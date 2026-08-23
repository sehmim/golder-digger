import { useApplication } from '../../application/ApplicationState'
import type { KnobStyle } from '../../application/ApplicationState'
import InterfaceMenu from '../../shared/components/InterfaceMenu'
import type { InterfaceId } from '../../shared/interfaceNavigation'

interface SettingsAppProps {
  onNavigate: (destination: InterfaceId) => void
}

const KNOB_STYLES: { id: KnobStyle; label: string }[] = [
  { id: 'classic', label: 'Classic' },
  { id: 'dark', label: 'Dark' },
  { id: 'minimal', label: 'Minimal' }
]

export default function SettingsApp({
  onNavigate
}: SettingsAppProps): React.JSX.Element {
  const { state, actions } = useApplication()

  return (
    <main className="settings-page" aria-label="Settings">
      <header className="settings-page__header">
        <h1>Settings</h1>
        <InterfaceMenu current="settings" onNavigate={onNavigate} />
      </header>

      <section className="settings-section">
        <h2>Knob</h2>
        <div className="settings-knob-options">
          {KNOB_STYLES.map((option) => (
            <button
              key={option.id}
              className="settings-knob-option"
              data-selected={state.settings.knobStyle === option.id || undefined}
              type="button"
              onClick={() => actions.setKnobStyle(option.id)}
            >
              <span className="settings-knob-preview" data-style={option.id} aria-hidden="true">
                <span />
              </span>
              <span>{option.label}</span>
            </button>
          ))}
        </div>
      </section>
    </main>
  )
}
