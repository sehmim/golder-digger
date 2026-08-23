import { useState } from 'react'
import type { ApplicationState } from '../../application/ApplicationState'
import type { GoldDiggerDiagnostics } from '../gold-digger/types'
import AnalysisFilesTab from './AnalysisFilesTab'
import ContextTab from './ContextTab'

interface DevAppProps {
  state: ApplicationState
  goldDigger: GoldDiggerDiagnostics
}

type DevTab = 'files' | 'context'

function StatePill({ active, children }: { active: boolean; children: React.ReactNode }) {
  return (
    <span className="dev-state-pill" data-active={active || undefined}>
      <span aria-hidden="true" />
      {children}
    </span>
  )
}

export default function DevApp({ state, goldDigger }: DevAppProps): React.JSX.Element {
  const [activeTab, setActiveTab] = useState<DevTab>('files')
  const projectName = state.project?.session.name ?? 'None connected'
  const snapshot = { application: state, interfaces: { goldDigger } }

  return (
    <section className="dev-page" aria-label="Developer window">
      <div className="dev-page__workspace">
        <aside className="dev-sidebar">
          <section className="dev-section">
            <div className="dev-state-summary">
              <article><span>Gold Digger step</span><strong>{goldDigger.currentStep}</strong></article>
              <article>
                <span>Backend</span>
                <StatePill active={state.api.ready}>{state.api.ready ? 'Ready' : 'Starting'}</StatePill>
              </article>
              <article><span>Folders</span><strong>{state.folders.length}</strong></article>
              <article><span>Jobs</span><strong>{state.ingest.jobs.length}</strong></article>
              <article><span>Project</span><strong title={projectName}>{projectName}</strong></article>
            </div>

            <section className="dev-state-panel">
              <header><h3>Folder roots</h3><span>{state.folders.length}</span></header>
              {state.folders.length > 0 ? (
                <ul className="dev-directory-list">
                  {state.folders.map((folder) => (
                    <li key={folder.id} title={folder.path}>
                      <span>{folder.name}</span>
                      {folder.analysis === 'unknown' ? <small>checking</small> : null}
                      {folder.analysis === 'analyzing' ? <small>analyzing</small> : null}
                    </li>
                  ))}
                </ul>
              ) : <p className="dev-state-empty">No folder roots.</p>}
            </section>

            <section className="dev-state-panel">
              <header>
                <h3>Gold Digger UI</h3>
                <StatePill active={!state.ingest.busy}>{state.ingest.busy ? 'Busy' : 'Idle'}</StatePill>
              </header>
              <dl className="dev-state-values">
                <div><dt>Visible panels</dt><dd>{goldDigger.visiblePanels.join(', ')}</dd></div>
                <div><dt>Leaving step</dt><dd>{goldDigger.leavingStep ?? '—'}</dd></div>
                <div><dt>Reached project</dt><dd>{String(goldDigger.hasReachedProject)}</dd></div>
                <div><dt>Ready jobs</dt><dd>{state.ingest.readyJobCount}</dd></div>
              </dl>
            </section>

            <details className="dev-state-raw">
              <summary><span>Raw state</span><small>JSON</small></summary>
              <pre>{JSON.stringify(snapshot, null, 2)}</pre>
            </details>
          </section>
        </aside>

        <section className="dev-inspector">
          <nav className="dev-tabs" aria-label="Developer data views">
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === 'files'}
              data-active={activeTab === 'files' || undefined}
              onClick={() => setActiveTab('files')}
            >
              Files
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === 'context'}
              data-active={activeTab === 'context' || undefined}
              onClick={() => setActiveTab('context')}
            >
              Context
            </button>
          </nav>
          <div className="dev-tab-panel" role="tabpanel">
            {activeTab === 'files' ? <AnalysisFilesTab application={state} /> : null}
            {activeTab === 'context' ? <ContextTab project={state.project} /> : null}
          </div>
        </section>
      </div>
    </section>
  )
}
