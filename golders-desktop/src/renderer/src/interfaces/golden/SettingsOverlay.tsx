import { useEffect, useRef } from 'react'
import { useApplication } from '../../application/ApplicationState'
import type { KnobStyle } from '../../application/ApplicationState'

const KNOB_STYLES: { id: KnobStyle; label: string }[] = [
  { id: 'classic', label: 'classic' },
  { id: 'dark', label: 'dark' },
  { id: 'minimal', label: 'minimal' }
]

interface SettingsOverlayProps {
  onClose: () => void
}

export default function SettingsOverlay({ onClose }: SettingsOverlayProps): React.JSX.Element {
  const { state, actions } = useApplication()
  const closeButton = useRef<HTMLButtonElement>(null)

  useEffect(() => closeButton.current?.focus(), [])

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [onClose])

  return (
    <div
      className="golden-overlay-layer"
      onMouseDown={(event) => {
        if (event.currentTarget === event.target) onClose()
      }}
    >
      <section
        className="golden-settings"
        role="dialog"
        aria-modal="true"
        aria-labelledby="golden-settings-title"
      >
        <header className="golden-settings__header">
          <span id="golden-settings-title">Settings</span>
          <button
            ref={closeButton}
            type="button"
            className="golden-overlay-close"
            aria-label="Close settings"
            onClick={onClose}
          >
            ✕
          </button>
        </header>

        <div className="golden-settings__body">
          <div className="golden-settings__block">
            <span className="golden-settings__label">Knob appearance</span>
            <div className="golden-settings__knob-options">
              {KNOB_STYLES.map((option) => (
                <button
                  key={option.id}
                  type="button"
                  data-selected={state.settings.knobStyle === option.id || undefined}
                  onClick={() => actions.setKnobStyle(option.id)}
                >
                  {option.label}
                </button>
              ))}
            </div>
          </div>

          <div className="golden-settings__row">
            <span>Dark mode</span>
            <button
              type="button"
              className="golden-toggle"
              data-on={state.settings.themeMode === 'dark' || undefined}
              role="switch"
              aria-checked={state.settings.themeMode === 'dark'}
              onClick={() =>
                actions.setThemeMode(state.settings.themeMode === 'dark' ? 'light' : 'dark')
              }
            >
              <span />
            </button>
          </div>

          <div className="golden-settings__row">
            <span>Only search enabled folders</span>
            <button
              type="button"
              className="golden-toggle"
              data-on={state.settings.folderFilteringEnabled || undefined}
              role="switch"
              aria-checked={state.settings.folderFilteringEnabled}
              onClick={() =>
                actions.setFolderFilteringEnabled(!state.settings.folderFilteringEnabled)
              }
            >
              <span />
            </button>
          </div>
        </div>
      </section>
    </div>
  )
}
