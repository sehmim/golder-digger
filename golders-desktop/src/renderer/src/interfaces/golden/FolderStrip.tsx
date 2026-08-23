import type { FolderRecord } from '../../application/ApplicationState'

interface FolderStripProps {
  folders: FolderRecord[]
  onOpenManager: (folderId?: string) => void
}

function FolderIcon(): React.JSX.Element {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M3.5 7.5h6l2-2h9v13h-17v-11Z" />
    </svg>
  )
}

export default function FolderStrip({
  folders,
  onOpenManager
}: FolderStripProps): React.JSX.Element {
  const recent = [...folders].sort((a, b) => b.addedAt.localeCompare(a.addedAt))
  const visibleFolder = recent[0]
  const remainingCount = Math.max(0, recent.length - 1)

  return (
    <div className="golden-folders" aria-label="Workspace folders">
      {visibleFolder ? (
        <div className="golden-folders__strip">
          <button
            type="button"
            className="golden-folder"
            data-analysis={visibleFolder.analysis}
            data-disabled={!visibleFolder.enabled || undefined}
            title={visibleFolder.path}
            aria-label={`${visibleFolder.name}${remainingCount > 0 ? ` and ${remainingCount} more ${remainingCount === 1 ? 'folder' : 'folders'}` : ''}`}
            onClick={() => onOpenManager(visibleFolder.id)}
          >
            <span className="golden-folder__icon">
              <FolderIcon />
            </span>
            <span className="golden-folder__name">{visibleFolder.name}</span>
            {remainingCount > 0 ? (
              <span className="golden-folder__remaining" aria-hidden="true">
                +{remainingCount}
              </span>
            ) : null}
            {visibleFolder.analysis !== 'available' ? (
              <span className="golden-folder__status" aria-label={visibleFolder.analysis} />
            ) : null}
          </button>
        </div>
      ) : null}

      {!visibleFolder ? (
        <button
          type="button"
          className="folder-manager-trigger"
          aria-label="Open folder manager"
          title="Folders"
          onClick={() => onOpenManager()}
        >
          <FolderIcon />
        </button>
      ) : null}
    </div>
  )
}
