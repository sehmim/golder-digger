/// <reference types="vite/client" />

import type { ApiStatus, SessionSet } from './lib/api'

declare global {
  interface Window {
    desktop: {
      selectDirectories: () => Promise<string[]>
      selectProject: () => Promise<string | null>

      apiStatus: () => Promise<ApiStatus>
      startIngest: (roots: string[]) => Promise<string>
      loadSet: (path: string) => Promise<SessionSet>
      analyze: (contextIds: string[], distance: number, k: number) => Promise<unknown>

      onIngestProgress: (handler: (status: unknown) => void) => () => void
      onIngestError: (handler: (payload: unknown) => void) => () => void
      onApiReady: (handler: (status: unknown) => void) => () => void
    }
  }
}
