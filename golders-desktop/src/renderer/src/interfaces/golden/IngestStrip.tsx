import { useApplication } from '../../application/ApplicationState'
import { progressOf } from '../../application/useIngest'
import { baseName } from '../../application/api'

export default function IngestStrip(): React.JSX.Element | null {
  const { state } = useApplication()
  const jobs = state.ingest.jobs
  if (jobs.length === 0) return null

  const job = jobs[jobs.length - 1]
  const progress = progressOf(job)

  return (
    <div className="golden-ingest-strip" aria-label="Ingest progress">
      <span className="golden-ingest-strip__count">
        {job.done} / {job.total}
      </span>
      <span className="golden-ingest-strip__track">
        <span
          className="golden-ingest-strip__fill"
          style={{ width: `${Math.round(progress * 100)}%` }}
        />
      </span>
      {job.currentFile ? (
        <span className="golden-ingest-strip__file">{baseName(job.currentFile)}</span>
      ) : null}
      {job.failed > 0 ? (
        <span className="golden-ingest-strip__failed">{job.failed} failed</span>
      ) : null}
    </div>
  )
}
