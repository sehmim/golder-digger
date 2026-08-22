import { baseName } from '../lib/api'
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
}

function meta(job: IngestJob): string {
  if (job.state === 'queued') return 'Queued'

  if (job.state === 'running') {
    if (job.total === 0) return 'Walking folder…'
    const file = job.currentFile ? ` · ${baseName(job.currentFile)}` : ''
    return `Ingesting · ${job.done} of ${job.total}${file}`
  }

  const failed = job.failed > 0 ? `, ${job.failed} failed` : ''
  return `${job.done} samples ingested${failed}`
}

export default function SourcesStep({
  jobs,
  apiReady,
  canContinue,
  onChoose,
  onDismiss,
  onClear,
  onContinue
}: SourcesStepProps): React.JSX.Element {
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

      {jobs.length > 0 ? (
        <div className="selections" aria-live="polite">
          <div className="selections-header">
            <span>
              {jobs.length} {jobs.length === 1 ? 'directory' : 'directories'} selected
            </span>
            <button className="clear-button" type="button" onClick={onClear}>
              Clear all
            </button>
          </div>

          <ul>
            {jobs.map((job) => (
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

      {canContinue ? (
        <button className="back-button" type="button" onClick={onContinue}>
          Continue to your project →
        </button>
      ) : null}
    </section>
  )
}
