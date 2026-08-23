/// <reference types="vite/client" />

import type {
  AnalyzeResult,
  ApiStatus,
  CorpusStats,
  EssentiaSummary,
  PresetList,
  SessionSet
} from './application/api'
import type { AnalysisFilesResult } from './interfaces/dev/types'

declare global {
  interface Window {
    desktop: {
      selectDirectories: () => Promise<string[]>
      selectProject: () => Promise<string | null>

      apiStatus: () => Promise<ApiStatus>
      openDevWindow: () => Promise<void>
      getDevSnapshot: () => Promise<unknown>
      publishDevSnapshot: (snapshot: unknown) => void
      folderStatus?: (roots: string[]) => Promise<{
        folders: { root: string; chunks: number }[]
      }>
      analysisFiles: (
        roots: string[] | null,
        limit: number,
        offset: number
      ) => Promise<AnalysisFilesResult>
      loadSettings?: () => Promise<unknown>
      saveSettings?: (settings: unknown) => Promise<void>
      pathExists?: (path: string) => Promise<boolean>
      startIngest: (roots: string[]) => Promise<string>
      loadSet: (path: string) => Promise<SessionSet>
      analyze: (
        contextIds: string[],
        /** null lets `preset` supply the position; the dial passes a number. */
        distance: number | null,
        k: number,
        sessionPath?: string | null,
        activeRoots?: string[] | null,
        preset?: string | null
      ) => Promise<AnalyzeResult>
      startEssentia: (root: string) => Promise<string>
      essentiaSummary: () => Promise<EssentiaSummary>
      presets: () => Promise<PresetList>
      corpusStats: () => Promise<CorpusStats>
      chunkAudio: (
        chunkId: string,
        options?: { bpm?: number | null; contextIds?: string[]; candidateOnly?: boolean }
      ) => Promise<ArrayBuffer>

      onIngestProgress: (handler: (status: unknown) => void) => () => void
      onIngestError: (handler: (payload: unknown) => void) => () => void
      onApiReady: (handler: (status: unknown) => void) => () => void
      onDevSnapshot: (handler: (snapshot: unknown) => void) => () => void
      onSettingsPageOpen?: (handler: () => void) => () => void
    }
  }
}
