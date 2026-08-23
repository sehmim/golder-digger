import { contextBridge, ipcRenderer } from 'electron'
import type { IpcRendererEvent } from 'electron'

interface AuditionOptions {
  bpm?: number | null
  contextIds?: string[]
  candidateOnly?: boolean
}

contextBridge.exposeInMainWorld('desktop', {
  selectDirectories: (): Promise<string[]> => ipcRenderer.invoke('directory:select'),
  selectProject: (): Promise<string | null> => ipcRenderer.invoke('project:select'),

  apiStatus: () => ipcRenderer.invoke('api:status'),
  openDevWindow: (): Promise<void> => ipcRenderer.invoke('dev:open'),
  getDevSnapshot: () => ipcRenderer.invoke('dev:snapshot:get'),
  publishDevSnapshot: (snapshot: unknown): void => ipcRenderer.send('dev:snapshot:publish', snapshot),
  folderStatus: (roots: string[]) => ipcRenderer.invoke('folders:status', roots),
  analysisFiles: (roots: string[] | null, limit: number, offset: number) =>
    ipcRenderer.invoke('dev:analysis-files', roots, limit, offset),
  loadSettings: () => ipcRenderer.invoke('settings:load'),
  saveSettings: (settings: unknown): Promise<void> => ipcRenderer.invoke('settings:save', settings),
  pathExists: (path: string): Promise<boolean> => ipcRenderer.invoke('path:exists', path),
  startIngest: (roots: string[]): Promise<string> => ipcRenderer.invoke('ingest:start', roots),
  loadSet: (path: string) => ipcRenderer.invoke('session:load', path),
  analyze: (
    contextIds: string[],
    distance: number,
    k: number,
    sessionPath?: string | null,
    activeRoots?: string[] | null
  ) => ipcRenderer.invoke(
    'session:analyze', contextIds, distance, k, sessionPath ?? null, activeRoots
  ),
  startEssentia: (root: string): Promise<string> => ipcRenderer.invoke('essentia:start', root),
  essentiaSummary: () => ipcRenderer.invoke('essentia:summary'),
  chunkAudio: (chunkId: string, options?: AuditionOptions): Promise<ArrayBuffer> =>
    ipcRenderer.invoke('chunk:audio', chunkId, options ?? {}),

  onIngestProgress: (handler: (status: unknown) => void): (() => void) => {
    const listener = (_event: IpcRendererEvent, status: unknown): void => handler(status)
    ipcRenderer.on('ingest:progress', listener)
    return () => ipcRenderer.off('ingest:progress', listener)
  },

  onIngestError: (handler: (payload: unknown) => void): (() => void) => {
    const listener = (_event: IpcRendererEvent, payload: unknown): void => handler(payload)
    ipcRenderer.on('ingest:error', listener)
    return () => ipcRenderer.off('ingest:error', listener)
  },

  onApiReady: (handler: (status: unknown) => void): (() => void) => {
    const listener = (_event: IpcRendererEvent, status: unknown): void => handler(status)
    ipcRenderer.on('api:ready', listener)
    return () => ipcRenderer.off('api:ready', listener)
  },

  onDevSnapshot: (handler: (snapshot: unknown) => void): (() => void) => {
    const listener = (_event: IpcRendererEvent, snapshot: unknown): void => handler(snapshot)
    ipcRenderer.on('dev:snapshot', listener)
    return () => ipcRenderer.off('dev:snapshot', listener)
  },

  onSettingsPageOpen: (handler: () => void): (() => void) => {
    const listener = (): void => handler()
    ipcRenderer.on('settings:open', listener)
    return () => ipcRenderer.off('settings:open', listener)
  }
})
