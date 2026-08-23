import { useCallback, useEffect, useRef, useState } from 'react'
import { baseName } from '../../../application/api'
import type { SessionSample, SessionSet } from '../../../application/api'
import { progressOf } from '../../../application/useIngest'
import type { IngestJob } from '../../../application/useIngest'

interface ProjectStepProps {
  ingestJobs: IngestJob[]
  startIngest: (roots: string[], label?: string) => Promise<string>
  sourceCount: number
  onBack: () => void
  onDig: (set: SessionSet) => void
  /** The set already being dug, when the user came back from that step. */
  dugSet: SessionSet | null
}

function matchedMeta(sample: SessionSample): string {
  const parts = [`${sample.chunks} ${sample.chunks === 1 ? 'chunk' : 'chunks'}`]
  // The classifier's guess is marked; a role read off the filename is not.
  if (sample.role) parts.push(sample.role_source === 'clap' ? `${sample.role}?` : sample.role)
  if (sample.bpm) parts.push(`${sample.bpm} BPM`)
  if (sample.tonic) parts.push(sample.tonic)
  parts.push(`${sample.method} match`)
  return parts.join(' · ')
}

/** Essentia only earns a line when it actually says something. */
function secondOpinion(sample: SessionSample): string | null {
  const view = sample.essentia
  if (!view) return null
  if (view.agrees === false) {
    return `essentia reads ${view.key ?? 'no key'}${view.bpm ? ` · ${view.bpm} BPM` : ''}`
  }
  return view.agrees ? 'essentia agrees' : null
}

function unmatchedMeta(sample: SessionSample): string {
  return sample.ingest_path ? `${sample.reason} · ready to ingest` : `${sample.reason} · not on disk`
}

export default function ProjectStep({
  ingestJobs,
  startIngest,
  sourceCount,
  onBack,
  onDig,
  dugSet
}: ProjectStepProps): React.JSX.Element {
  // Seeded from the dig step's set so coming back shows the resolved card, not
  // an empty dropzone. This component unmounts during the dig, so its own state
  // would not survive the round trip.
  const [set, setSet] = useState<SessionSet | null>(dugSet)
  const [reading, setReading] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [jobId, setJobId] = useState<string | null>(null)

  // Once per set path, so a failed sample cannot loop the auto-ingest, and
  // coming back from the dig step does not immediately yank the screen forward.
  const autoIngested = useRef(new Set<string>())
  const autoAdvanced = useRef(new Set<string>())

  const job = ingestJobs.find((candidate) => candidate.jobId === jobId) ?? null

  const load = useCallback(async (path: string) => {
    setReading(true)
    setError(null)

    try {
      setSet(await window.desktop.loadSet(path))
    } catch (cause) {
      setSet(null)
      setError(String(cause instanceof Error ? cause.message : cause))
    } finally {
      setReading(false)
    }
  }, [])

  // Ingesting the missing samples changes the answer, so the set is resolved again.
  useEffect(() => {
    if (!set || job?.state !== 'finished') return

    setJobId(null)
    void load(set.session.path)
  }, [job?.state, set, load])

  async function chooseProject(): Promise<void> {
    const path = await window.desktop.selectProject()
    if (path) await load(path)
  }

  async function ingestMissing(): Promise<void> {
    if (!set) return

    const paths = set.unmatched
      .map((sample) => sample.ingest_path)
      .filter((path): path is string => Boolean(path))

    if (paths.length === 0) return

    setJobId(
      await startIngest(paths, `${paths.length} ${paths.length === 1 ? 'sample' : 'samples'}`)
    )
  }

  const missing = set?.unmatched.filter((sample) => sample.ingest_path).length ?? 0

  // The whole step is automatic: resolve, ingest what the set references but the
  // corpus lacks, resolve again, then hand over to the dig. The buttons remain as
  // the manual override, not the expected path.
  useEffect(() => {
    if (!set || job || reading) return
    const path = set.session.path

    if (missing > 0 && !autoIngested.current.has(path)) {
      autoIngested.current.add(path)
      void ingestMissing()
      return
    }

    // A set that was already dug advances only by hand -- the user came back on
    // purpose, and yanking them forward again would fight the back button.
    const alreadyDug = dugSet?.session.path === path
    const settled = missing === 0 || autoIngested.current.has(path)
    if (!alreadyDug && settled && set.context_ids.length > 0 && !autoAdvanced.current.has(path)) {
      // long enough to read the resolved list before it slides away; the ref is
      // marked when it fires, so an interim re-render just reschedules it
      const advance = setTimeout(() => {
        autoAdvanced.current.add(path)
        onDig(set)
      }, 1400)
      return () => clearTimeout(advance)
    }
  })

  return (
    <section className="project-connect">
      <div className="copy">
        <p className="eyebrow">Connect project</p>
        <h1>Add your Ableton session</h1>
        <p className="description">
          Gold Digger reads your set, then matches every sample it references against your
          ingested library.
        </p>
      </div>

      {set === null ? (
        <div
          className={`dropzone${dragging ? ' is-dragging' : ''}${reading ? ' is-reading' : ''}`}
          onDragOver={(event) => {
            event.preventDefault()
            if (!reading) setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(event) => {
            event.preventDefault()
            setDragging(false)
            // Only the dialog yields a real path, so a drop opens the picker instead.
            if (!reading) void chooseProject()
          }}
        >
          {reading ? (
            <div className="reading" aria-live="polite">
              <span className="spinner spinner--large" aria-hidden="true" />
              <p className="dropzone-hint">Reading set · hashing referenced samples</p>
            </div>
          ) : (
            <>
              <div className="project-icon" aria-hidden="true">
                <svg viewBox="0 0 24 24" role="img">
                  <path d="M4 5.5h4v13H4v-13Zm6 3h4v10h-4v-10Zm6-3h4v13h-4v-13Z" />
                </svg>
              </div>
              <p className="dropzone-title">Choose your .als file</p>
              <p className="dropzone-hint">Live 10, 11 and 12 sets are supported.</p>
              <button className="primary-button" type="button" onClick={() => void chooseProject()}>
                Choose project
              </button>
            </>
          )}
        </div>
      ) : (
        <div className="set-card" aria-live="polite">
          <header className="set-head">
            <div>
              <p className="set-name">{set.session.name}</p>
              <p className="set-meta">
                {set.session.tempo ? `${set.session.tempo} BPM` : 'tempo unknown'}
                {set.session.key
                  ? ` · ${set.session.key}`
                  : set.session.in_key
                    ? ''
                    : ' · no key set in Live'}
                {' · '}
                {set.matched.length} of {set.session.samples} samples in your library
              </p>
              {set.session.creator ? (
                <p className="set-meta set-meta--soft">{set.session.creator}</p>
              ) : null}
            </div>
            <button className="clear-button" type="button" onClick={() => void chooseProject()}>
              Change set
            </button>
          </header>

          <ul className="sample-list">
            {set.matched.map((sample) => (
              <li key={sample.resolved_path ?? sample.name} data-status="ready">
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M4 12.5l5 5 11-11" />
                </svg>
                <span className="entry" title={sample.resolved_path}>
                  <span className="entry-name">{sample.name}</span>
                  <span className="entry-meta">{matchedMeta(sample)}</span>
                  {sample.tags?.length ? (
                    <span className="tags">
                      {sample.tags.map((tag) => (
                        <span className="tag" key={tag}>
                          {tag}
                        </span>
                      ))}
                    </span>
                  ) : null}
                  {secondOpinion(sample) ? (
                    <span className="entry-aside" data-clash={sample.essentia?.agrees === false || undefined}>
                      {secondOpinion(sample)}
                    </span>
                  ) : null}
                </span>
              </li>
            ))}

            {set.unmatched.map((sample) => (
              <li key={sample.name + sample.candidates[0]} data-status="missing">
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M12 7v6m0 3.5v.5M3.8 19h16.4L12 4.5 3.8 19Z" />
                </svg>
                <span className="entry" title={sample.candidates[0]}>
                  <span className="entry-name">{sample.name}</span>
                  <span className="entry-meta">{unmatchedMeta(sample)}</span>
                </span>
              </li>
            ))}
          </ul>

          {job ? (
            <div className="job-row">
              <span className="spinner" aria-hidden="true" />
              <span className="entry">
                <span className="entry-name">Ingesting {job.label}</span>
                <span className="entry-meta">
                  {job.total > 0
                    ? `${job.done} of ${job.total}${
                        job.currentFile ? ` · ${baseName(job.currentFile)}` : ''
                      }`
                    : 'Starting'}
                </span>
                <span className="entry-track" aria-hidden="true">
                  <span className="entry-fill" style={{ transform: `scaleX(${progressOf(job)})` }} />
                </span>
              </span>
            </div>
          ) : missing > 0 ? (
            <button className="secondary-button" type="button" onClick={() => void ingestMissing()}>
              Ingest {missing} missing {missing === 1 ? 'sample' : 'samples'}
            </button>
          ) : null}

          {set.context_ids.length === 0 ? (
            <p className="analysis">
              {job ? 'Ingesting the set’s samples…' : 'No samples resolved yet'}
            </p>
          ) : dugSet?.session.path === set.session.path ? (
            <button
              className="primary-button primary-button--wide"
              type="button"
              onClick={() => onDig(set)}
            >
              Back to digging · {set.context_ids.length} context chunks
            </button>
          ) : (
            <p className="analysis" aria-live="polite">
              {job
                ? `Preparing ${set.context_ids.length} context chunks…`
                : `Starting the dig · ${set.context_ids.length} context chunks`}
            </p>
          )}
        </div>
      )}

      {error ? <p className="error">{error}</p> : null}

      <button className="back-button" type="button" onClick={onBack}>
        ← {sourceCount} {sourceCount === 1 ? 'directory' : 'directories'} ingested
      </button>
    </section>
  )
}
