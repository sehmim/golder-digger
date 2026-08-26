/**
 * The Python side of Gold Digger runs as a child process serving localhost.
 * Main owns the process and the HTTP client; the renderer only ever sees IPC,
 * so contextIsolation stays intact and there is no CSP or CORS story.
 */
import { spawn } from 'node:child_process'
import type { ChildProcess } from 'node:child_process'
import { existsSync, mkdirSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { app } from 'electron'

const HOST = '127.0.0.1'
const PORT = 8420
const BASE = `http://${HOST}:${PORT}`

/** Importing the package pulls in torch, so first boot is slow even in mock mode. */
const BOOT_TIMEOUT_MS = 90_000
const BOOT_POLL_MS = 400

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

export interface SessionSample {
  name: string
  candidates: string[]
  method?: 'hash' | 'path' | 'basename'
  resolved_path?: string
  chunk_ids?: string[]
  chunks?: number
  role?: string | null
  role_source?: string | null
  tags?: string[]
  essentia?: EssentiaView | null
  bpm?: number | null
  tonic?: string | null
  reason?: string
  ingest_path?: string | null
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
  /** True when the pool was too thin and the gate had to open below the preset's floor. */
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

let child: ChildProcess | null = null
let ready = false
let bootError: string | null = null
let booting: Promise<void> | null = null

/** The repo checkout, which is this app's parent directory in development. */
function repoRoot(): string {
  return process.env.GOLDDIGGER_ROOT || resolve(app.getAppPath(), '..')
}

/**
 * A packaged app carries its own engine in Resources/engine: a relocatable
 * Python with the goldigger package installed into its site-packages, assembled
 * by scripts/package-engine.sh. Null in development, where the repo venv is
 * the engine.
 */
function packagedPython(): string | null {
  if (!app.isPackaged) return null
  const python = join(process.resourcesPath, 'engine', 'python', 'bin', 'python3')
  return existsSync(python) ? python : null
}

function pythonBin(): string {
  if (process.env.GOLDDIGGER_PYTHON) return process.env.GOLDDIGGER_PYTHON
  const packaged = packagedPython()
  if (packaged) return packaged
  const venv = join(repoRoot(), '.venv', 'bin', 'python3')
  return existsSync(venv) ? venv : 'python3'
}

/**
 * The routes this app cannot run without.
 *
 * An already-listening server is adopted rather than replaced, so a `serve` left
 * over from an earlier session gets used silently and then 404s every route
 * added since it started. This used to be guarded by one marker key somebody had
 * to remember to move; nobody ever did, so from the first commit onward it was
 * present in every build and discriminated nothing -- /session/midi and
 * /session/lines both shipped behind a check that could not see them. /health
 * now reports its own route table, and this is the list checked against it.
 *
 * Add a route here when you add a call below. `tests/test_health_contract.py`
 * parses this literal and fails if the engine does not serve one of them.
 */
const REQUIRED_ROUTES = [
  '/health',
  '/ingest',
  '/ingest/status/{job_id}',
  '/library/files',
  '/folders/status',
  '/corpus/stats',
  '/presets',
  '/essentia',
  '/essentia/summary',
  '/session/als',
  '/session/analyze',
  '/session/lines',
  '/chunk/{chunk_id}/peaks',
  '/chunk/{chunk_id}/audio'
]

/** Routes the adopted server does not serve. Empty means it is new enough. */
function missingRoutes(body: Record<string, unknown>): string[] {
  const served = body.routes
  // A server predating the routes list cannot answer the question, and every
  // build old enough to lack it is old enough to be refused.
  if (!Array.isArray(served)) return [...REQUIRED_ROUTES]
  const have = new Set(served as string[])
  return REQUIRED_ROUTES.filter((route) => !have.has(route))
}

async function healthBody(signal?: AbortSignal): Promise<Record<string, unknown> | null> {
  try {
    const response = await fetch(`${BASE}/health`, { signal })
    return response.ok ? ((await response.json()) as Record<string, unknown>) : null
  } catch {
    return null
  }
}

async function health(signal?: AbortSignal): Promise<boolean> {
  return (await healthBody(signal)) !== null
}

export function status(): { ready: boolean; error: string | null } {
  return { ready, error: bootError }
}

export async function start(): Promise<void> {
  if (booting) return booting

  booting = (async () => {
    // A server already listening (a `golddigger serve` in a terminal) is used as is.
    const existing = await healthBody()
    if (existing) {
      const missing = missingRoutes(existing)
      if (missing.length) {
        bootError =
          `the API already running on :${PORT} is older than this app — it does not ` +
          `serve ${missing.join(', ')}. Restart it with ./start.sh --restart`
        throw new Error(bootError)
      }
      ready = true
      return
    }

    const bin = pythonBin()
    // Packaged, the bundle is read-only: the engine writes its database and job
    // artifacts to userData (GOLDDIGGER_DATA), and reads bundled model weights
    // when the engine was assembled with --models.
    const packaged = packagedPython() !== null
    const dataDir = app.getPath('userData')
    if (packaged) mkdirSync(dataDir, { recursive: true })
    const models = join(process.resourcesPath, 'engine', 'models')
    child = spawn(bin, ['-m', 'uvicorn', 'goldigger.api:app', '--host', HOST, '--port', String(PORT)], {
      cwd: packaged ? dataDir : repoRoot(),
      env: {
        // The engine defaults to mock because the test suite and the CLI want it
        // to. The app is the product: under mock the CLAP vector is synthesized
        // from the file hash, so "sounds like" — the entire DISTANCE dial — means
        // nothing. GOLDDIGGER_MOCK in the environment still wins, for debugging.
        GOLDDIGGER_MOCK: '0',
        ...(packaged ? { GOLDDIGGER_DATA: dataDir } : {}),
        ...(packaged && existsSync(models) ? { HF_HOME: models } : {}),
        ...process.env,
        PYTHONUNBUFFERED: '1'
      },
      stdio: ['ignore', 'pipe', 'pipe']
    })

    child.stdout?.on('data', (chunk) => process.stdout.write(`[api] ${chunk}`))
    child.stderr?.on('data', (chunk) => process.stderr.write(`[api] ${chunk}`))
    child.on('exit', (code) => {
      ready = false
      if (code !== 0 && code !== null) bootError = `python exited with code ${code}`
    })
    child.on('error', (error) => {
      bootError = `could not start ${bin}: ${error.message}`
    })

    const deadline = Date.now() + BOOT_TIMEOUT_MS
    while (Date.now() < deadline) {
      if (bootError) throw new Error(bootError)
      if (await health()) {
        ready = true
        return
      }
      await new Promise((done) => setTimeout(done, BOOT_POLL_MS))
    }

    bootError = `api did not answer on ${BASE} within ${BOOT_TIMEOUT_MS / 1000}s`
    throw new Error(bootError)
  })()

  return booting
}

export function stop(): void {
  child?.kill()
  child = null
  ready = false
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { 'content-type': 'application/json', ...(init?.headers ?? {}) }
  })

  if (!response.ok) {
    const body = await response.text()
    let detail = body
    try {
      detail = JSON.parse(body).detail ?? body
    } catch {
      /* a non-JSON error body is already the best message available */
    }
    throw new Error(`${response.status} ${detail}`)
  }

  return (await response.json()) as T
}

export function startIngest(roots: string[]): Promise<{ job_id: string }> {
  return request('/ingest', { method: 'POST', body: JSON.stringify({ roots }) })
}

export function startEssentia(root: string): Promise<{ job_id: string }> {
  return request('/essentia', { method: 'POST', body: JSON.stringify({ root }) })
}

export function essentiaSummary(): Promise<EssentiaSummary> {
  return request('/essentia/summary')
}

export function jobStatus(jobId: string): Promise<JobStatus> {
  return request(`/ingest/status/${jobId}`)
}

export function loadSet(path: string): Promise<SessionSet> {
  return request('/session/als', { method: 'POST', body: JSON.stringify({ path }) })
}

export function folderStatus(roots: string[]): Promise<{ folders: { root: string; chunks: number }[] }> {
  return request('/folders/status', { method: 'POST', body: JSON.stringify({ roots }) })
}

/** One of the five scoring postures served by GET /presets. */
export interface Preset {
  key: string
  name: string
  distance: number
  fit_floor: number
  bandwidth: number
  redundancy: number
  role_mode: 'strict' | 'normal' | 'loose' | 'off'
  blurb: string
  notes: string
}

export interface PresetList {
  presets: Preset[]
  default: Preset
  role_modes: Record<string, { same: number; pair: number; unknown: number }>
  fit_floor_min: number
}

/** Whether the corpus can support the scoring at all -- see GET /corpus/stats. */
export interface CorpusStats {
  chunks: number
  files: number
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

export function presets(): Promise<PresetList> {
  return request('/presets')
}

export interface ChunkPeaks {
  chunk_id: string
  buckets: number
  duration: number
  /** The chunk's own tempo. */
  bpm: number | null
  /** The tempo it was rendered to, matching playback. */
  target_bpm: number | null
  stretched: boolean
  /** [min, max] per bucket, of the audio that will sound. */
  peaks: [number, number][]
}

export function chunkPeaks(
  chunkId: string,
  buckets = 240,
  bpm?: number | null
): Promise<ChunkPeaks> {
  const query = new URLSearchParams({ buckets: String(buckets) })
  if (bpm) query.set('bpm', String(bpm))
  return request(`/chunk/${encodeURIComponent(chunkId)}/peaks?${query.toString()}`)
}

export function corpusStats(): Promise<CorpusStats> {
  return request('/corpus/stats')
}

export function analysisFiles(
  roots: string[] | null,
  limit: number,
  offset: number
): Promise<AnalysisFilesResult> {
  return request('/library/files', {
    method: 'POST',
    body: JSON.stringify({ roots, limit, offset })
  })
}

/** One station on a line: a candidate, how far out it sits, and why. */
export interface Stop {
  chunk_id: string
  path: string
  role: string | null
  bpm: number | null
  tonic: string | null
  fit: number
  /** Position along this line only, 0 near to 1 far. Not the DISTANCE dial. */
  position: number
  /** Faithful by construction: the term that actually moved this stop out. */
  why: string
}

export interface Line {
  key: string
  /** Semantic token, not hex — styles.css owns the Montreal palette. */
  colour: 'green' | 'orange' | 'blue' | 'yellow'
  blurb: string
  stops: Stop[]
  /** False when the library cannot answer this line — drawn greyed out. */
  available: boolean
  fit_floor: number
  fit_floor_requested: number
  /** True when this line had to open its gate to find enough stops. */
  fit_floor_relaxed: boolean
}

export interface Network {
  lines: Line[]
  interchanges: { chunk_id: string; lines: string[] }[]
  preset: string
  fit_floor_requested: number
}

/** The transit map: every line out of this context, with its stops. */
export function sessionLines(contextIds: string[], stops?: number,
                             sessionPath?: string | null,
                             activeRoots?: string[] | null,
                             preset?: string | null): Promise<Network> {
  return request('/session/lines', {
    method: 'POST',
    body: JSON.stringify({
      context_ids: contextIds,
      stops: stops ?? null,
      session_path: sessionPath ?? null,
      active_roots: activeRoots,
      preset: preset ?? null
    })
  })
}

export function analyze(contextIds: string[], distance: number | null, k: number,
                       sessionPath?: string | null,
                       activeRoots?: string[] | null,
                       preset?: string | null): Promise<AnalyzeResult> {
  return request('/session/analyze', {
    method: 'POST',
    body: JSON.stringify({
      context_ids: contextIds,
      // null lets the preset supply its own position; the dial passes a number
      distance,
      k,
      session_path: sessionPath ?? null,
      active_roots: activeRoots,
      preset: preset ?? null
    })
  })
}

export interface AuditionOptions {
  /** Session tempo. The candidate is time-stretched to it before it sounds. */
  bpm?: number | null
  /** The session's own chunks, mixed underneath so the pair is judged together. */
  contextIds?: string[]
  /** Hear the candidate alone instead of over the session. */
  candidateOnly?: boolean
}

/**
 * The chunk's audio as bytes, not a URL: the renderer has no route to the API,
 * and a media element pointing at localhost would be a second way in.
 *
 * Rendered through /session/preview rather than the raw chunk endpoint, because
 * a candidate heard at its own tempo gets judged on the mismatch instead of on
 * whether it works. Pitch is never shifted -- see goldigger/audition.py.
 */
export async function chunkAudio(
  chunkId: string,
  options: AuditionOptions = {}
): Promise<ArrayBuffer> {
  const query = new URLSearchParams({ candidate: chunkId })
  if (options.bpm) query.set('bpm', String(options.bpm))
  if (options.candidateOnly) query.set('candidate_only', 'true')
  for (const id of options.contextIds ?? []) query.append('context', id)

  const response = await fetch(`${BASE}/session/preview?${query.toString()}`)
  if (!response.ok) throw new Error(`${response.status} could not render ${chunkId}`)
  return response.arrayBuffer()
}
