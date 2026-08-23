import type { ApplicationState } from '../../application/ApplicationState'
import type { GoldDiggerDiagnostics } from '../gold-digger/types'

export interface DevSnapshot {
  application: ApplicationState
  interfaces: {
    goldDigger: GoldDiggerDiagnostics
  }
}

export interface AnalysisFile {
  path: string
  file_hash: string
  duration: number | null
  status: string | null
  ingested_at: string | null
  chunks: number
  bpm: number | null
  keys: string[]
  roles: string[]
  synthetic: boolean
  essentia: boolean
}

export interface AnalysisFilesResult {
  total: number
  count: number
  offset: number
  files: AnalysisFile[]
}
