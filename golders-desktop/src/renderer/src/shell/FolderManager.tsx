import { useEffect, useRef } from 'react'
import { useApplication } from '../application/ApplicationState'

interface FolderManagerProps {
  focusedFolderId: string | null
  onClose: () => void
}

export default function FolderManager({
  focusedFolderId,
  onClose
}: FolderManagerProps): React.JSX.Element {
  const { state, actions } = useApplication()
  const focused = useRef<HTMLLIElement>(null)
  const closeButton = useRef<HTMLButtonElement>(null)

  useEffect(() => closeButton.current?.focus(), [])

  useEffect(() => {
    focused.current?.scrollIntoView({ block: 'nearest' })
  }, [focusedFolderId])

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [onClose])

  return (
    <div className="folder-manager-layer" onMouseDown={(event) => {
      if (event.currentTarget === event.target) onClose()
    }}>
      <section className="folder-manager" role="dialog" aria-modal="true" aria-labelledby="folder-manager-title">
        <header className="folder-manager__header">
          <h1 id="folder-manager-title">Folders</h1>
          <button ref={closeButton} type="button" className="folder-manager__close" aria-label="Close folder manager" onClick={onClose}>
            ×
          </button>
        </header>

        {state.folders.length > 0 ? (
          <ul className="folder-manager__list">
            {state.folders.map((folder) => {
              const isFocused = folder.id === focusedFolderId
              const status = !folder.enabled
                ? 'disabled'
                : folder.analysis === 'available'
                  ? null
                  : folder.analysis === 'unknown'
                    ? 'checking'
                    : folder.analysis
              return (
                <li
                  key={folder.id}
                  ref={isFocused ? focused : undefined}
                  data-focused={isFocused || undefined}
                  data-disabled={!folder.enabled || undefined}
                >
                  <div className="folder-manager__identity">
                    <strong title={folder.path}>{folder.name}</strong>
                    <span title={folder.path}>{folder.path}</span>
                  </div>
                  {status ? (
                    <span
                      className="folder-manager__status"
                      data-analysis={folder.enabled ? folder.analysis : undefined}
                    >
                      {status}
                    </span>
                  ) : null}
                  <div className="folder-manager__actions">
                    {folder.analysis === 'failed' ? (
                      <button type="button" onClick={() => void actions.retryFolder(folder.id)}>Retry</button>
                    ) : null}
                    <button
                      type="button"
                      className="golden-toggle"
                      data-on={folder.enabled || undefined}
                      role="switch"
                      aria-checked={folder.enabled}
                      aria-label={folder.enabled ? 'Disable folder' : 'Enable folder'}
                      onClick={() => actions.setFolderEnabled(folder.id, !folder.enabled)}
                    >
                      <span />
                    </button>
                    <button
                      type="button"
                      className="folder-manager__remove"
                      onClick={() => actions.removeFolder(folder.id)}
                    >
                      Remove from workspace
                    </button>
                  </div>
                </li>
              )
            })}
          </ul>
        ) : (
          <p className="folder-manager__empty">No folders</p>
        )}

        <button type="button" className="folder-manager__add" onClick={() => void actions.chooseDirectories()}>
          Add folders
        </button>
      </section>
    </div>
  )
}
