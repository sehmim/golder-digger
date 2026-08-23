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

/** Essentia's whole-file second opinion, when the pass has seen this file. */
export interface EssentiaView {
  key: string | null
  key_confidence: number | null
  bpm: number | null
  bpm_confidence: number | null
  danceability: number | null
  /** null when neither tool named a key, which is not a disagreement. */
  agrees: boolean | null
}

export interface EssentiaSummary {
  /** How the extractor can run here; null means it cannot. */
  mode: 'native' | 'docker' | null
  files: number
  covered: number
  agree: number
  disagree: number
  no_key: number
}

/** One of the five scoring postures served by GET /presets, safest first. */
export interface Preset {
  key: string
  name: string
  /** Target novelty percentile. */
  distance: number
  /** Minimum Fit a candidate needs to be considered at all. */
  fit_floor: number
  /** How tightly the novelty target is held. */
  bandwidth: number
  /** Penalty for resembling something already picked. */
  redundancy: number
  role_mode: 'strict' | 'normal' | 'loose' | 'off'
  blurb: string
  /** The honest paragraph, including what this preset gives up. */
  notes: string
}

export interface PresetList {
  presets: Preset[]
  default: Preset
  role_modes: Record<string, { same: number; pair: number; unknown: number }>
  fit_floor_min: number
}

/** Waveform for one chunk, at its own tempo. */
export interface ChunkPeaks {
  chunk_id: string
  buckets: number
  duration: number
  /** The chunk's own tempo. */
  bpm: number | null
  /** The tempo it was rendered to, matching playback. */
  target_bpm: number | null
  stretched: boolean
  /** [min, max] per bucket. Both, so a waveform keeps its asymmetry. */
  peaks: [number, number][]
}

/** Whether the corpus can support the scoring at all. */
export interface CorpusStats {
  chunks: number
  files: number
  /** measured = a real CLAP vector; unknown predates the column and is untrusted. */
  provenance: { measured: number; synthetic: number; unknown: number }
  key: {
    strong: number
    absent: number
    mean_confidence: number
    histogram: { from: number; to: number; count: number }[]
  }
  tempo: { with_bpm: number; histogram: { label: string; count: number }[] }
  roles: {
    unassigned: number
    breakdown: { role: string | null; source: string | null; count: number }[]
  }
  essentia: EssentiaSummary
}

/** One <SampleRef> from a Live set, after resolution against the corpus. */
export interface SessionSample {
  name: string
  candidates: string[]
  /** How the file was found. Present on matched samples only. Weakest last. */
  method?: 'hash' | 'path' | 'basename' | 'basename+size'
  resolved_path?: string
  chunk_ids?: string[]
  chunks?: number
  role?: string | null
  /** 'filename' when a human named it, 'clap' when the tag classifier guessed. */
  role_source?: string | null
  tags?: string[]
  essentia?: EssentiaView | null
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
  role_source: string | null
  tags: string[]
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
  /** Context fields Live stated outright and the engine took over the inferred ones. */
  session_context: ('bpm' | 'tonic')[]
  context: { bpm: number | null; tonic: string | null; roles: string[] }
  /** True when any ranked chunk's CLAP vector was synthesized from its file hash. */
  synthetic_novelty: boolean
  /** How many of `corpus_size` those are — the dial is skewed in proportion. */
  synthetic_chunks: number
  /** Which posture scored this, and the numbers it actually used. */
  preset: string
  fit_floor_requested: number
  /** True when the pool was too thin and the gate opened below the preset's floor. */
  fit_floor_relaxed: boolean
  bandwidth: number
  redundancy: number
  role_mode: string
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
