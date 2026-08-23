import { useEffect, useMemo, useState } from 'react'
import type { ApplicationState, FolderRecord } from '../../application/ApplicationState'
import type { AnalysisFilesResult } from './types'

const PAGE_SIZE = 100

function underRoot(path: string, root: string): boolean {
  const prefix = root.endsWith('/') ? root : `${root}/`
  return path === root || path.startsWith(prefix)
}

function folderFor(path: string, folders: FolderRecord[]): FolderRecord | undefined {
  return folders
    .filter((folder) => underRoot(path, folder.path))
    .sort((a, b) => b.path.length - a.path.length)[0]
}

function durationLabel(seconds: number | null): string {
  if (seconds === null) return '—'
  const minutes = Math.floor(seconds / 60)
  const remainder = Math.round(seconds % 60)
  return minutes > 0 ? `${minutes}:${String(remainder).padStart(2, '0')}` : `${remainder}s`
}

interface AnalysisFilesTabProps {
  application: ApplicationState
}

export default function AnalysisFilesTab({
  application
}: AnalysisFilesTabProps): React.JSX.Element {
  const [selectedRoot, setSelectedRoot] = useState<string>('all')
  const [offset, setOffset] = useState(0)
  const [refresh, setRefresh] = useState(0)
  const [result, setResult] = useState<AnalysisFilesResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const roots = useMemo<string[] | null>(() => {
    if (selectedRoot !== 'all') return [selectedRoot]
    return application.settings.folderFilteringEnabled
      ? application.folders.map((folder) => folder.path)
      : null
  }, [application.folders, application.settings.folderFilteringEnabled, selectedRoot])
  const rootsKey = roots?.join('\u0000') ?? '*'

  useEffect(() => {
    if (selectedRoot === 'all') return
    if (!application.folders.some((folder) => folder.path === selectedRoot)) {
      setSelectedRoot('all')
      setOffset(0)
    }
  }, [application.folders, selectedRoot])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    void window.desktop
      .analysisFiles(roots, PAGE_SIZE, offset)
      .then((next) => {
        if (cancelled) return
        setResult(next)
        setError(null)
      })
      .catch((cause) => {
        if (cancelled) return
        setError(cause instanceof Error ? cause.message : String(cause))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [offset, refresh, rootsKey])

  const files = result?.files ?? []
  const end = result ? Math.min(result.offset + result.count, result.total) : 0

  return (
    <section className="dev-files" aria-label="Analyzed files">
      <header className="dev-files__toolbar">
        <div className="dev-folder-filter" aria-label="Filter analyzed files by folder">
          <button
            type="button"
            data-active={selectedRoot === 'all' || undefined}
            onClick={() => { setSelectedRoot('all'); setOffset(0) }}
          >
            All
          </button>
          {application.folders.map((folder) => (
            <button
              key={folder.id}
              type="button"
              data-active={selectedRoot === folder.path || undefined}
              title={folder.path}
              onClick={() => { setSelectedRoot(folder.path); setOffset(0) }}
            >
              {folder.name}
            </button>
          ))}
        </div>
        <button type="button" className="dev-files__refresh" onClick={() => setRefresh((value) => value + 1)}>
          Refresh
        </button>
      </header>

      <div className="dev-files__summary">
        <span>{result ? `${result.total.toLocaleString()} analyzed files` : 'Loading files'}</span>
        {result && result.total > 0 ? <span>{result.offset + 1}–{end}</span> : null}
      </div>

      {error ? <p className="dev-files__message error">{error}</p> : null}
      {!error && !loading && files.length === 0 ? (
        <p className="dev-files__message">No analyzed files in this folder selection.</p>
      ) : null}

      {files.length > 0 ? (
        <div className="dev-file-table" data-loading={loading || undefined}>
          <div className="dev-file-table__head" aria-hidden="true">
            <span>File</span><span>Folder</span><span>Analysis</span><span>Musical</span><span>Chunks</span>
          </div>
          <ol>
            {files.map((file) => {
              const folder = folderFor(file.path, application.folders)
              const name = file.path.split('/').filter(Boolean).at(-1) ?? file.path
              const analysis = [
                file.synthetic ? 'synthetic' : 'measured',
                file.essentia ? 'Essentia' : null,
                durationLabel(file.duration)
              ].filter(Boolean).join(' · ')
              const musical = [
                file.bpm === null ? null : `${file.bpm} BPM`,
                file.keys.join('/'),
                file.roles.join(', ')
              ].filter(Boolean).join(' · ') || '—'

              return (
                <li key={`${file.file_hash}:${file.path}`}>
                  <span className="dev-file-name" title={file.path}>{name}</span>
                  <span title={folder?.path ?? file.path}>{folder?.name ?? 'Corpus'}</span>
                  <span title={file.ingested_at ?? undefined}>{analysis}</span>
                  <span title={musical}>{musical}</span>
                  <span>{file.chunks}</span>
                </li>
              )
            })}
          </ol>
        </div>
      ) : null}

      <footer className="dev-files__pagination">
        <button type="button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
          Previous
        </button>
        <button type="button" disabled={!result || end >= result.total} onClick={() => setOffset(offset + PAGE_SIZE)}>
          Next
        </button>
      </footer>
    </section>
  )
}
