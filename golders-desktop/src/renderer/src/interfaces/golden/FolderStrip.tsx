import type { FolderRecord } from '../../application/ApplicationState'

interface FolderStripProps {
  folders: FolderRecord[]
  onOpenManager: (folderId?: string) => void
}

export default function FolderStrip({
  folders,
  onOpenManager
}: FolderStripProps): React.JSX.Element {
  const recent = [...folders].sort((a, b) => b.addedAt.localeCompare(a.addedAt))

  return (
    <div className="golden-folders" aria-label="Workspace folders">
      {recent.length > 0 ? (
        <div className="golden-folders__strip">
          {recent.map((folder) => (
            <button
              key={folder.id}
              type="button"
              className="golden-folder"
              data-analysis={folder.analysis}
              data-disabled={!folder.enabled || undefined}
              title={folder.path}
              onClick={() => onOpenManager(folder.id)}
            >
              <span className="golden-folder__name">{folder.name}</span>
              {folder.analysis !== 'available' ? (
                <span className="golden-folder__status" aria-label={folder.analysis} />
              ) : null}
            </button>
          ))}
        </div>
      ) : null}

      <button
        type="button"
        className="folder-manager-trigger"
        aria-label="Open folder manager"
        title="Folders"
        onClick={() => onOpenManager()}
      >
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M3.5 7.5h6l2-2h9v13h-17v-11Z" />
        </svg>
      </button>
    </div>
  )
}
