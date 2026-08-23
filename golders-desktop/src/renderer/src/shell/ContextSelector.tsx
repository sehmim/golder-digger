import { useEffect, useRef, useState } from 'react'
import { useApplication } from '../application/ApplicationState'

interface ContextSelectorProps {
  onClose: () => void
}

function tonalCenter(key: string | null): string | null {
  return key?.match(/^[A-G](?:#|b)?/)?.[0] ?? null
}

export default function ContextSelector({ onClose }: ContextSelectorProps): React.JSX.Element {
  const { state, actions } = useApplication()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const closeButton = useRef<HTMLButtonElement>(null)

  useEffect(() => closeButton.current?.focus(), [])

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent): void => {
      if (event.key === 'Escape' && !loading) onClose()
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [loading, onClose])

  async function chooseProject(): Promise<void> {
    const path = await window.desktop.selectProject()
    if (!path) return

    setLoading(true)
    setError(null)
    try {
      actions.setProject(await window.desktop.loadSet(path))
      onClose()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause))
    } finally {
      setLoading(false)
    }
  }

  const project = state.project
  const center = tonalCenter(project?.session.key ?? null)

  return (
    <div
      className="context-selector-layer"
      onMouseDown={(event) => {
        if (!loading && event.currentTarget === event.target) onClose()
      }}
    >
      <section
        className="context-selector"
        role="dialog"
        aria-modal="true"
        aria-labelledby="context-selector-title"
      >
        <header className="context-selector__header">
          <h1 id="context-selector-title">Context</h1>
          <button
            ref={closeButton}
            type="button"
            className="context-selector__close"
            aria-label="Close context selector"
            onClick={onClose}
            disabled={loading}
          >
            ×
          </button>
        </header>

        <div className="context-selector__source">
          <div className="context-selector__identity">
            <strong>{project?.session.name ?? 'Ableton project'}</strong>
            {project ? (
              <span>
                {project.session.tempo === null
                  ? 'Tempo unknown'
                  : `${Math.round(project.session.tempo)} BPM`}
                {center ? ` · ${center}` : ''}
              </span>
            ) : null}
          </div>
          <button type="button" onClick={() => void chooseProject()} disabled={loading}>
            {loading ? 'Reading…' : project ? 'Change' : 'Choose .als'}
          </button>
        </div>

        {error ? <p className="context-selector__error">{error}</p> : null}

        {project ? (
          <button
            type="button"
            className="context-selector__remove"
            onClick={() => actions.setProject(null)}
            disabled={loading}
          >
            Clear context
          </button>
        ) : null}
      </section>
    </div>
  )
}
