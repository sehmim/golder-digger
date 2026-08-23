import type { SessionSample, SessionSet } from '../../application/api'

interface ContextTabProps {
  project: SessionSet | null
}

function sampleReading(sample: SessionSample): string {
  return [sample.bpm ? `${Math.round(sample.bpm)} BPM` : null, sample.tonic]
    .filter(Boolean)
    .join(' · ') || '—'
}

export default function ContextTab({ project }: ContextTabProps): React.JSX.Element {
  if (!project) {
    return <p className="dev-files__message">No context connected.</p>
  }

  const references = [
    ...project.matched.map((sample) => ({ sample, status: 'matched' as const })),
    ...project.unmatched.map((sample) => ({ sample, status: 'unmatched' as const }))
  ]

  return (
    <section className="dev-context">
      <dl className="dev-context__summary">
        <div><dt>Tempo</dt><dd>{project.session.tempo === null ? '—' : `${project.session.tempo} BPM`}</dd></div>
        <div><dt>Declared key</dt><dd>{project.session.key ?? '—'}</dd></div>
        <div><dt>Context chunks</dt><dd>{project.context_ids.length}</dd></div>
      </dl>

      <dl className="dev-context__source">
        <div><dt>Project</dt><dd>{project.session.name}</dd></div>
        <div><dt>Path</dt><dd title={project.session.path}>{project.session.path}</dd></div>
        <div><dt>Creator</dt><dd>{project.session.creator ?? '—'}</dd></div>
        <div><dt>Key enabled in Live</dt><dd>{String(project.session.in_key)}</dd></div>
        <div><dt>Referenced files</dt><dd>{project.session.samples}</dd></div>
        <div><dt>Matched / unmatched</dt><dd>{project.matched.length} / {project.unmatched.length}</dd></div>
      </dl>

      <div className="dev-context__table">
        <div className="dev-context__table-head" aria-hidden="true">
          <span>Referenced audio</span><span>Status</span><span>Match</span><span>Chunks</span><span>Reading</span>
        </div>
        <ol>
          {references.map(({ sample, status }, index) => {
            const path = sample.resolved_path ?? sample.ingest_path ?? sample.candidates[0]
            const statusLabel = status === 'matched'
              ? 'matched'
              : sample.ingest_path
                ? 'not analyzed'
                : 'unresolved'
            return (
              <li key={`${sample.name}-${path ?? index}`} data-status={statusLabel}>
                <span className="dev-context__sample" title={path}>
                  <strong>{sample.name}</strong>
                  <small>{path ?? '—'}</small>
                </span>
                <span>{statusLabel}</span>
                <span>{sample.method ?? '—'}</span>
                <span>{sample.chunks ?? '—'}</span>
                <span>{sampleReading(sample)}</span>
              </li>
            )
          })}
        </ol>
      </div>
    </section>
  )
}
