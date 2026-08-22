/**
 * The Python side of Gold Digger runs as a child process serving localhost.
 * Main owns the process and the HTTP client; the renderer only ever sees IPC,
 * so contextIsolation stays intact and there is no CSP or CORS story.
 */
import { spawn } from 'node:child_process'
import type { ChildProcess } from 'node:child_process'
import { existsSync } from 'node:fs'
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

export interface SessionSample {
  name: string
  candidates: string[]
  method?: 'hash' | 'path' | 'basename'
  resolved_path?: string
  chunk_ids?: string[]
  chunks?: number
  role?: string | null
  bpm?: number | null
  tonic?: string | null
  reason?: string
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

let child: ChildProcess | null = null
let ready = false
let bootError: string | null = null
let booting: Promise<void> | null = null

/** The repo checkout, which is this app's parent directory in development. */
function repoRoot(): string {
  return process.env.GOLDDIGGER_ROOT || resolve(app.getAppPath(), '..')
}

function pythonBin(): string {
  if (process.env.GOLDDIGGER_PYTHON) return process.env.GOLDDIGGER_PYTHON
  const venv = join(repoRoot(), '.venv', 'bin', 'python3')
  return existsSync(venv) ? venv : 'python3'
}

async function health(signal?: AbortSignal): Promise<boolean> {
  try {
    const response = await fetch(`${BASE}/health`, { signal })
    return response.ok
  } catch {
    return false
  }
}

export function status(): { ready: boolean; error: string | null } {
  return { ready, error: bootError }
}

export async function start(): Promise<void> {
  if (booting) return booting

  booting = (async () => {
    // A server already listening (a `golddigger serve` in a terminal) is used as is.
    if (await health()) {
      ready = true
      return
    }

    const bin = pythonBin()
    child = spawn(bin, ['-m', 'uvicorn', 'goldigger.api:app', '--host', HOST, '--port', String(PORT)], {
      cwd: repoRoot(),
      env: { ...process.env, PYTHONUNBUFFERED: '1' },
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

export function jobStatus(jobId: string): Promise<JobStatus> {
  return request(`/ingest/status/${jobId}`)
}

export function loadSet(path: string): Promise<SessionSet> {
  return request('/session/als', { method: 'POST', body: JSON.stringify({ path }) })
}

export function analyze(contextIds: string[], distance: number, k: number): Promise<AnalyzeResult> {
  return request('/session/analyze', {
    method: 'POST',
    body: JSON.stringify({ context_ids: contextIds, distance, k })
  })
}

/**
 * The chunk's audio as bytes, not a URL: the renderer has no route to the API,
 * and a media element pointing at localhost would be a second way in.
 */
export async function chunkAudio(chunkId: string): Promise<ArrayBuffer> {
  const response = await fetch(`${BASE}/chunk/${encodeURIComponent(chunkId)}/audio`)
  if (!response.ok) throw new Error(`${response.status} could not render ${chunkId}`)
  return response.arrayBuffer()
}
