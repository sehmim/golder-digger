import { createContext, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { baseName } from './api'
import type { ApiStatus, SessionSet } from './api'
import { useIngest } from './useIngest'
import type { IngestJob } from './useIngest'

export type KnobStyle = 'classic' | 'dark' | 'minimal'
export type ThemeMode = 'light' | 'dark'
export type FolderAnalysisStatus = 'unknown' | 'analyzing' | 'available' | 'failed'

/** User intent stored in settings.json. Runtime facts are deliberately excluded. */
export interface RegisteredFolder {
  id: string
  path: string
  name: string
  enabled: boolean
  addedAt: string
  lastUsedAt: string
}

/** A registered folder combined with facts verified during this application run. */
export interface FolderRecord extends RegisteredFolder {
  analysis: FolderAnalysisStatus
  reachable: boolean
}

interface PersistedSettings {
  version: 1
  knobStyle: KnobStyle
  themeMode: ThemeMode
  /** Once enabled, an empty active list means "search nothing", not "search everything". */
  folderFilteringEnabled: boolean
  folders: RegisteredFolder[]
}

export interface ApplicationState {
  api: ApiStatus
  /** Registered folders that still exist on disk. */
  folders: FolderRecord[]
  /** null preserves the legacy whole-corpus behavior; [] intentionally selects no corpus. */
  activeFolderRoots: string[] | null
  /** Compatibility view for existing UI while it moves to FolderRecord. */
  directories: string[]
  ingest: {
    jobs: IngestJob[]
    readyJobCount: number
    busy: boolean
    error: string | null
  }
  project: SessionSet | null
  settings: {
    loaded: boolean
    knobStyle: KnobStyle
    themeMode: ThemeMode
    folderFilteringEnabled: boolean
  }
}

export interface ApplicationActions {
  chooseDirectories: () => Promise<void>
  startIngest: (roots: string[], label?: string) => Promise<string>
  runEssentia: (roots: string[]) => Promise<void>
  dismissJob: (jobId: string) => void
  clearJobs: () => void
  setProject: (project: SessionSet | null) => void
  setKnobStyle: (style: KnobStyle) => void
  setThemeMode: (mode: ThemeMode) => void
  setFolderFilteringEnabled: (enabled: boolean) => void
  setFolderEnabled: (folderId: string, enabled: boolean) => void
  retryFolder: (folderId: string) => Promise<void>
  removeFolder: (folderId: string) => void
}

interface ApplicationContextValue {
  state: ApplicationState
  actions: ApplicationActions
}

const EMPTY_SETTINGS: PersistedSettings = {
  version: 1,
  knobStyle: 'classic',
  themeMode: 'light',
  folderFilteringEnabled: false,
  folders: []
}

const ApplicationContext = createContext<ApplicationContextValue | null>(null)

function isKnobStyle(value: unknown): value is KnobStyle {
  return value === 'classic' || value === 'dark' || value === 'minimal'
}

function isThemeMode(value: unknown): value is ThemeMode {
  return value === 'light' || value === 'dark'
}

function isRegisteredFolder(value: unknown): value is RegisteredFolder {
  if (!value || typeof value !== 'object') return false
  const folder = value as Partial<RegisteredFolder>
  return (
    typeof folder.id === 'string' &&
    typeof folder.path === 'string' &&
    typeof folder.name === 'string' &&
    typeof folder.enabled === 'boolean' &&
    typeof folder.addedAt === 'string' &&
    typeof folder.lastUsedAt === 'string'
  )
}

function readSettings(raw: unknown): PersistedSettings {
  if (!raw || typeof raw !== 'object') return EMPTY_SETTINGS

  const candidate = raw as {
    knobStyle?: unknown
    themeMode?: unknown
    folderFilteringEnabled?: unknown
    folders?: unknown
  }
  const folders = Array.isArray(candidate.folders)
    ? candidate.folders.filter(isRegisteredFolder).map((folder) => ({
        id: folder.id,
        path: folder.path,
        name: folder.name,
        enabled: folder.enabled,
        addedAt: folder.addedAt,
        lastUsedAt: folder.lastUsedAt
      }))
    : []

  return {
    version: 1,
    knobStyle: isKnobStyle(candidate.knobStyle) ? candidate.knobStyle : 'classic',
    // Settings written before dark mode existed did not have this field.
    themeMode: isThemeMode(candidate.themeMode) ? candidate.themeMode : 'light',
    // Settings written by the first persistence draft did not have this flag.
    folderFilteringEnabled:
      typeof candidate.folderFilteringEnabled === 'boolean'
        ? candidate.folderFilteringEnabled
        : folders.length > 0,
    folders
  }
}

function persistedFolder(folder: FolderRecord): RegisteredFolder {
  const { id, path, name, enabled, addedAt, lastUsedAt } = folder
  return { id, path, name, enabled, addedAt, lastUsedAt }
}

export function ApplicationStateProvider({ children }: { children: ReactNode }): React.JSX.Element {
  const { jobs, startIngest, startEssentia, dismissJob, clearJobs, error } = useIngest()
  const [api, setApi] = useState<ApiStatus>({ ready: false, error: null })
  const [project, setProject] = useState<SessionSet | null>(null)
  const [knobStyle, setKnobStyle] = useState<KnobStyle>('classic')
  const [themeMode, setThemeMode] = useState<ThemeMode>('light')
  const [folders, setFolders] = useState<FolderRecord[]>([])
  const [folderFilteringEnabled, setFolderFilteringEnabled] = useState(false)
  const [settingsLoaded, setSettingsLoaded] = useState(false)

  useEffect(() => {
    const off = window.desktop.onApiReady((status) => setApi(status as ApiStatus))
    void window.desktop.apiStatus().then(setApi)
    return off
  }, [])

  useEffect(() => {
    let cancelled = false

    async function hydrate(): Promise<void> {
      try {
        const persisted = readSettings(await window.desktop.loadSettings?.())
        const hydratedFolders = await Promise.all(
          persisted.folders.map(async (folder): Promise<FolderRecord> => ({
            ...folder,
            analysis: 'unknown',
            reachable: window.desktop.pathExists
              ? await window.desktop.pathExists(folder.path)
              : true
          }))
        )

        if (cancelled) return
        setKnobStyle(persisted.knobStyle)
        setThemeMode(persisted.themeMode)
        setFolderFilteringEnabled(persisted.folderFilteringEnabled)
        setFolders(hydratedFolders)
      } catch (cause) {
        console.error('Could not load application settings', cause)
      } finally {
        if (!cancelled) setSettingsLoaded(true)
      }
    }

    void hydrate()
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (!settingsLoaded || !window.desktop.saveSettings) return
    const settings: PersistedSettings = {
      version: 1,
      knobStyle,
      themeMode,
      folderFilteringEnabled,
      folders: folders.map(persistedFolder)
    }
    void window.desktop
      .saveSettings(settings)
      .catch((cause) => console.error('Could not save application settings', cause))
  }, [folderFilteringEnabled, folders, knobStyle, themeMode, settingsLoaded])

  // The renderer root is the one DOM node every themed surface inherits from.
  useEffect(() => {
    document.documentElement.dataset.theme = themeMode
  }, [themeMode])

  // Analysis availability belongs to the corpus, so verify it rather than trusting settings.
  useEffect(() => {
    const unresolved = folders.filter(
      (folder) => folder.reachable && folder.analysis === 'unknown'
    )
    if (!api.ready || unresolved.length === 0 || !window.desktop.folderStatus) return

    let cancelled = false
    void window.desktop
      .folderStatus(unresolved.map((folder) => folder.path))
      .then(({ folders: statuses }) => {
        if (cancelled) return
        const chunksByRoot = new Map(statuses.map((status) => [status.root, status.chunks]))
        setFolders((current) =>
          current.map((folder) => {
            if (!chunksByRoot.has(folder.path) || folder.analysis !== 'unknown') return folder
            return {
              ...folder,
              analysis: (chunksByRoot.get(folder.path) ?? 0) > 0 ? 'available' : 'failed'
            }
          })
        )
      })
      .catch((cause) => console.error('Could not verify folder analysis', cause))

    return () => {
      cancelled = true
    }
  }, [api.ready, folders])

  useEffect(() => {
    const finishedRoots = new Set(
      jobs
        .filter((job) => job.kind === 'ingest' && job.state === 'finished')
        .flatMap((job) => job.roots)
    )
    if (finishedRoots.size === 0) return

    setFolders((current) =>
      current.map((folder) =>
        finishedRoots.has(folder.path) && folder.analysis !== 'available'
          ? { ...folder, analysis: 'available' }
          : folder
      )
    )
  }, [jobs])

  const value = useMemo<ApplicationContextValue>(() => {
    const readyJobCount = jobs.filter(
      (job) => job.kind === 'ingest' && job.state === 'finished'
    ).length
    const visibleFolders = folders.filter((folder) => folder.reachable)
    const activeFolderRoots = folderFilteringEnabled
      ? visibleFolders
          .filter((folder) => folder.enabled && folder.analysis === 'available')
          .map((folder) => folder.path)
      : null

    return {
      state: {
        api,
        folders: visibleFolders,
        activeFolderRoots,
        directories: visibleFolders.map((folder) => folder.path),
        ingest: {
          jobs,
          readyJobCount,
          busy: jobs.some((job) => job.state !== 'finished'),
          error
        },
        project,
        settings: { loaded: settingsLoaded, knobStyle, themeMode, folderFilteringEnabled }
      },
      actions: {
        chooseDirectories: async () => {
          const selected = await window.desktop.selectDirectories()
          if (selected.length === 0) return

          const now = new Date().toISOString()
          setFolderFilteringEnabled(true)
          setFolders((current) => {
            const byPath = new Map(current.map((folder) => [folder.path, folder]))
            for (const path of selected) {
              const existing = byPath.get(path)
              byPath.set(path, {
                id: existing?.id ?? crypto.randomUUID(),
                path,
                name: baseName(path),
                analysis: 'analyzing',
                enabled: existing?.enabled ?? true,
                reachable: true,
                addedAt: existing?.addedAt ?? now,
                lastUsedAt: now
              })
            }
            return [...byPath.values()]
          })

          for (const path of selected) {
            try {
              await startIngest([path])
            } catch {
              setFolders((current) =>
                current.map((folder) =>
                  folder.path === path ? { ...folder, analysis: 'failed' } : folder
                )
              )
            }
          }
        },
        startIngest,
        runEssentia: async (roots) => {
          for (const root of roots) await startEssentia(root)
        },
        dismissJob,
        clearJobs,
        setProject,
        setKnobStyle,
        setThemeMode,
        setFolderFilteringEnabled,
        setFolderEnabled: (folderId, enabled) =>
          setFolders((current) =>
            current.map((folder) =>
              folder.id === folderId
                ? { ...folder, enabled, lastUsedAt: new Date().toISOString() }
                : folder
            )
          ),
        retryFolder: async (folderId) => {
          const folder = folders.find((candidate) => candidate.id === folderId)
          if (!folder) return
          setFolders((current) =>
            current.map((candidate) =>
              candidate.id === folderId ? { ...candidate, analysis: 'analyzing' } : candidate
            )
          )
          try {
            await startIngest([folder.path])
          } catch {
            setFolders((current) =>
              current.map((candidate) =>
                candidate.id === folderId ? { ...candidate, analysis: 'failed' } : candidate
              )
            )
          }
        },
        // Removes only the application record. Audio and cached analysis remain untouched.
        removeFolder: (folderId) =>
          setFolders((current) => current.filter((folder) => folder.id !== folderId))
      }
    }
  }, [
    api,
    clearJobs,
    dismissJob,
    error,
    folderFilteringEnabled,
    folders,
    jobs,
    knobStyle,
    themeMode,
    project,
    settingsLoaded,
    startEssentia,
    startIngest
  ])

  return <ApplicationContext.Provider value={value}>{children}</ApplicationContext.Provider>
}

export function useApplication(): ApplicationContextValue {
  const value = useContext(ApplicationContext)
  if (!value) throw new Error('useApplication must be used inside ApplicationStateProvider')
  return value
}
