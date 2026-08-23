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
  startIngest: (roots: string[]): Promise<string> => ipcRenderer.invoke('ingest:start', roots),
  loadSet: (path: string) => ipcRenderer.invoke('session:load', path),
  analyze: (contextIds: string[], distance: number, k: number, sessionPath?: string | null) =>
    ipcRenderer.invoke('session:analyze', contextIds, distance, k, sessionPath ?? null),
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

  onDevPageToggle: (handler: () => void): (() => void) => {
    const listener = (): void => handler()
    ipcRenderer.on('dev:toggle', listener)
    return () => ipcRenderer.off('dev:toggle', listener)
  },

  onSettingsPageOpen: (handler: () => void): (() => void) => {
    const listener = (): void => handler()
    ipcRenderer.on('settings:open', listener)
    return () => ipcRenderer.off('settings:open', listener)
  }
})
