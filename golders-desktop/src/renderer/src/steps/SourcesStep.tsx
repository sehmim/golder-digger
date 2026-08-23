import { useCallback, useEffect, useState } from 'react'
import { baseName } from '../lib/api'
import type { EssentiaSummary } from '../lib/api'
import { progressOf } from '../lib/useIngest'
import type { IngestJob } from '../lib/useIngest'

const FOLDER_PATH =
  'M3.5 6.5a2 2 0 0 1 2-2h4l2 2h7a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2v-11Z'

interface SourcesStepProps {
  jobs: IngestJob[]
  apiReady: boolean
  canContinue: boolean
  onChoose: () => void
  onDismiss: (jobId: string) => void
  onClear: () => void
  onContinue: () => void
  onRunEssentia: (roots: string[]) => void
}

function meta(job: IngestJob): string {
  if (job.kind === 'essentia') {
    if (job.failed > 0) return job.currentFile ?? 'failed'
    if (job.state === 'finished') return job.currentFile ?? 'done'
    return `${job.currentFile ?? 'starting'}…`
  }

  if (job.state === 'queued') return 'Queued'

  if (job.state === 'running') {
    if (job.total === 0) return 'Walking folder…'
    const file = job.currentFile ? ` · ${baseName(job.currentFile)}` : ''
    return `Ingesting · ${job.done} of ${job.total}${file}`
  }

  const failed = job.failed > 0 ? `, ${job.failed} failed` : ''
  // A finished job carries a footnote when it repaired rows instead of
  // re-extracting them -- otherwise a skipped folder and a repaired one read the same.
  const repairs = job.currentFile ? ` · ${job.currentFile}` : ''
  return `${job.done} samples ingested${failed}${repairs}`
}

/** Essentia coverage in one line, in the terms the button is offering. */
function summaryLine(summary: EssentiaSummary): string {
  if (summary.mode === null) {
    return 'needs essentia (pip install essentia) or a running docker'
  }
  if (summary.covered === 0) {
    return 'runs during ingest · nothing analysed yet'
  }
  const parts = [
    summary.covered >= summary.files
      ? `all ${summary.files} files analysed`
      : `${summary.covered} of ${summary.files} files analysed`
  ]
  // Only meaningful in real mode; in mock mode Essentia supplied the key itself.
  if (summary.agree) parts.push(`key agrees on ${summary.agree}`)
  if (summary.disagree) parts.push(`differs on ${summary.disagree}`)
  return parts.join(' · ')
}

export default function SourcesStep({
  jobs,
  apiReady,
  canContinue,
  onChoose,
  onDismiss,
  onClear,
  onContinue,
  onRunEssentia
}: SourcesStepProps): React.JSX.Element {
  const [summary, setSummary] = useState<EssentiaSummary | null>(null)

  const ingestJobs = jobs.filter((job) => job.kind === 'ingest')
  const essentiaJobs = jobs.filter((job) => job.kind === 'essentia')

  const finishedRoots = ingestJobs
    .filter((job) => job.state === 'finished')
    .flatMap((job) => job.roots)

  const running = essentiaJobs.some((job) => job.state !== 'finished')
  // Every finished job changes what the summary would say, so it is re-read on
  // each of them rather than once on mount.
  const settled = jobs.filter((job) => job.state === 'finished').length

  const refresh = useCallback(() => {
    if (!apiReady) return
    void window.desktop.essentiaSummary().then(setSummary).catch(() => setSummary(null))
  }, [apiReady])

  useEffect(refresh, [refresh, settled])

  return (
    <section className="directory-picker">
      <div className="folder-icon" aria-hidden="true">
        <svg viewBox="0 0 24 24" role="img">
          <path d={FOLDER_PATH} />
        </svg>
      </div>

      <div className="copy">
        <p className="eyebrow">Get started</p>
        <h1>Select your sample directories</h1>
        <p className="description">
          Choose the folders that contain the audio files you want Gold Digger to explore.
        </p>
      </div>

      <button className="primary-button" type="button" onClick={onChoose} disabled={!apiReady}>
        {jobs.length > 0 ? 'Add directories' : 'Choose directories'}
      </button>

      {ingestJobs.length > 0 ? (
        <div className="selections" aria-live="polite">
          <div className="selections-header">
            <span>
              {ingestJobs.length} {ingestJobs.length === 1 ? 'directory' : 'directories'} selected
            </span>
            <button className="clear-button" type="button" onClick={onClear}>
              Clear all
            </button>
          </div>

          <ul>
            {ingestJobs.map((job) => (
              <li key={job.jobId} data-status={job.state === 'finished' ? 'ready' : 'scanning'}>
                {job.state === 'finished' ? (
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d={FOLDER_PATH} />
                  </svg>
                ) : (
                  <span className="spinner" aria-hidden="true" />
                )}

                <span className="entry" title={job.currentFile ?? job.label}>
                  <span className="entry-name">{job.label}</span>
                  <span className="entry-meta">{meta(job)}</span>
                  <span className="entry-track" aria-hidden="true">
                    <span
                      className="entry-fill"
                      style={{ transform: `scaleX(${progressOf(job)})` }}
                    />
                  </span>
                </span>

                {job.state === 'finished' ? (
                  <button
                    className="remove-button"
                    type="button"
                    aria-label={`Remove ${job.label}`}
                    onClick={() => onDismiss(job.jobId)}
                  >
                    ×
                  </button>
                ) : (
                  <span />
                )}
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="hint">
          {apiReady ? 'Select multiple folders with Command-click.' : 'Starting the audio engine…'}
        </p>
      )}

      {jobs.some((job) => job.kind === 'ingest' && job.state !== 'finished') &&
      summary?.mode === 'native' ? (
        <p className="hint">Each file is also measured with Essentia — about a second each.</p>
      ) : null}

      {finishedRoots.length > 0 ? (
        <div className="selections second-opinion" aria-live="polite">
          <div className="selections-header">
            <span>Second opinion</span>
            <button
              className="clear-button"
              type="button"
              disabled={running || summary?.mode === null}
              onClick={() => onRunEssentia(finishedRoots)}
            >
              {running ? 'Running…' : summary?.covered ? 'Re-run' : 'Run Essentia'}
            </button>
          </div>

          <p className="summary-line">{summary ? summaryLine(summary) : 'checking…'}</p>

          {essentiaJobs.length > 0 ? (
            <ul>
              {essentiaJobs.map((job) => (
                <li
                  key={job.jobId}
                  data-status={job.state === 'finished' ? 'ready' : 'scanning'}
                  data-failed={job.failed > 0 || undefined}
                >
                  {job.state !== 'finished' ? (
                    <span className="spinner" aria-hidden="true" />
                  ) : job.failed > 0 ? (
                    <svg viewBox="0 0 24 24" aria-hidden="true">
                      <path d="M12 7v6m0 3.5v.5M3.8 19h16.4L12 4.5 3.8 19Z" />
                    </svg>
                  ) : (
                    <svg viewBox="0 0 24 24" aria-hidden="true">
                      <path d="M4 12.5l5 5 11-11" />
                    </svg>
                  )}

                  <span className="entry" title={job.roots[0]}>
                    <span className="entry-name">{job.label}</span>
                    <span className="entry-meta">{meta(job)}</span>
                  </span>

                  <span />
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}

      {canContinue ? (
        <button className="back-button" type="button" onClick={onContinue}>
          Continue to your project →
        </button>
      ) : null}
    </section>
  )
}
