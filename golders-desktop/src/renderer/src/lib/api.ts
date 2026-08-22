/**
 * Shapes returned by the Python API, as they arrive through IPC.
 * Mirrors `src/main/api.ts`; the two sides do not share a module because they
 * build into separate bundles.
 */

export interface JobStatus {
  job_id: string
  root: string
  state: 'queued' | 'running' | 'finished'
  total: number
  done: number
  failed: number
  message: string | null
}

/** One <SampleRef> from a Live set, after resolution against the corpus. */
export interface SessionSample {
  name: string
  candidates: string[]
  /** How the file was found. Present on matched samples only. */
  method?: 'hash' | 'path' | 'basename'
  resolved_path?: string
  chunk_ids?: string[]
  chunks?: number
  role?: string | null
  bpm?: number | null
  tonic?: string | null
  /** Why it did not resolve. Present on unmatched samples only. */
  reason?: string
  /** Set when the file is on disk but absent from the corpus, so it can be ingested. */
  ingest_path?: string | null
}

/** One row of the results list: a chunk the engine picked for the context. */
export interface Candidate {
  chunk_id: string
  path: string
  role: string | null
  bpm: number | null
  tonic: string | null
  is_major: boolean
  key_confidence: number
  fit: number
  novelty: number
  components: { H: number; R: number; P: number }
}

export interface AnalyzeResult {
  distance: number
  fit_floor: number
  corpus_size: number
  count: number
  results: Candidate[]
}

export interface SessionSet {
  session: {
    name: string
    path: string
    creator: string | null
    tempo: number | null
    key: string | null
    in_key: boolean
    samples: number
  }
  matched: SessionSample[]
  unmatched: SessionSample[]
  context_ids: string[]
}

export interface ApiStatus {
  ready: boolean
  error: string | null
}

export function baseName(path: string): string {
  const parts = path.split('/').filter(Boolean)
  return parts[parts.length - 1] ?? path
}
