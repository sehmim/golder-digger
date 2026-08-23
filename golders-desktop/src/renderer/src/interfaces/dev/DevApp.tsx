import { useApplication } from '../../application/ApplicationState'
import InterfaceMenu from '../../shared/components/InterfaceMenu'
import type { InterfaceId } from '../../shared/interfaceNavigation'
import type { GoldDiggerDiagnostics } from '../gold-digger/types'

interface DevAppProps {
  goldDigger: GoldDiggerDiagnostics
  onNavigate: (destination: InterfaceId) => void
}

function StatePill({ active, children }: { active: boolean; children: React.ReactNode }) {
  return (
    <span className="dev-state-pill" data-active={active || undefined}>
      <span aria-hidden="true" />
      {children}
    </span>
  )
}

export default function DevApp({
  goldDigger,
  onNavigate
}: DevAppProps): React.JSX.Element {
  const { state } = useApplication()
  const projectName = state.project?.session.name ?? 'None connected'
  const snapshot = { application: state, interfaces: { goldDigger } }

  return (
    <section className="dev-page" aria-label="Developer interface">
      <header className="dev-page__header">
        <h1>Dev</h1>

        <InterfaceMenu current="dev" onNavigate={onNavigate} />
      </header>

      <div className="dev-page__canvas">
        <section className="dev-section">
          <h2>State</h2>

          <div className="dev-state-summary">
            <article>
              <span>Gold Digger step</span>
              <strong>{goldDigger.currentStep}</strong>
            </article>
            <article>
              <span>Backend</span>
              <StatePill active={state.api.ready}>
                {state.api.ready ? 'Ready' : 'Starting'}
              </StatePill>
            </article>
            <article>
              <span>Directories</span>
              <strong>{state.directories.length}</strong>
            </article>
            <article>
              <span>Jobs</span>
              <strong>{state.ingest.jobs.length}</strong>
            </article>
            <article className="dev-state-summary__project">
              <span>Project</span>
              <strong title={projectName}>{projectName}</strong>
            </article>
          </div>

          <div className="dev-state-grid">
            <section className="dev-state-panel">
              <header>
                <h3>Tracked directory roots</h3>
                <span>{state.directories.length}</span>
              </header>
              {state.directories.length > 0 ? (
                <ul className="dev-directory-list">
                  {state.directories.map((directory) => (
                    <li key={directory} title={directory}>
                      {directory}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="dev-state-empty">No directory roots are being tracked.</p>
              )}
            </section>

            <section className="dev-state-panel">
              <header>
                <h3>Gold Digger UI</h3>
                <StatePill active={!state.ingest.busy}>
                  {state.ingest.busy ? 'Ingest busy' : 'Ingest idle'}
                </StatePill>
              </header>
              <dl className="dev-state-values">
                <div><dt>Visible panels</dt><dd>{goldDigger.visiblePanels.join(', ')}</dd></div>
                <div><dt>Leaving step</dt><dd>{goldDigger.leavingStep ?? '—'}</dd></div>
                <div><dt>Reached project</dt><dd>{String(goldDigger.hasReachedProject)}</dd></div>
                <div><dt>Ready ingest jobs</dt><dd>{state.ingest.readyJobCount}</dd></div>
              </dl>
            </section>
          </div>

          <details className="dev-state-raw">
            <summary><span>Raw state snapshot</span><small>JSON</small></summary>
            <pre>{JSON.stringify(snapshot, null, 2)}</pre>
          </details>
        </section>
      </div>
    </section>
  )
}
