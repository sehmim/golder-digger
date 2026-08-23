import { useEffect, useState } from 'react'
import type { ApplicationState } from '../../application/ApplicationState'
import type { CorpusStats } from '../../application/api'
import type { GoldDiggerDiagnostics } from '../gold-digger/types'
import AnalysisFilesTab from './AnalysisFilesTab'
import ContextTab from './ContextTab'
import CorpusTab from './CorpusTab'
import PresetsTab from './PresetsTab'

interface DevAppProps {
  state: ApplicationState
  goldDigger: GoldDiggerDiagnostics
}

type DevTab = 'corpus' | 'presets' | 'files' | 'context'

function StatePill({ active, children }: { active: boolean; children: React.ReactNode }) {
  return (
    <span className="dev-state-pill" data-active={active || undefined}>
      <span aria-hidden="true" />
      {children}
    </span>
  )
}

export default function DevApp({ state, goldDigger }: DevAppProps): React.JSX.Element {
  const [activeTab, setActiveTab] = useState<DevTab>('corpus')
  const [stats, setStats] = useState<CorpusStats | null>(null)
  const projectName = state.project?.session.name ?? 'None connected'
  const snapshot = { application: state, interfaces: { goldDigger } }

  // The summary below describes the corpus, not this window. Renderer counters
  // belong in Raw state -- a job count is bookkeeping for an ingest that has
  // already finished and says nothing about whether the engine can discriminate.
  useEffect(() => {
    let cancelled = false
    void window.desktop
      .corpusStats()
      .then((next) => !cancelled && setStats(next))
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [state.ingest.busy])

  const untrusted = stats
    ? stats.provenance.synthetic + stats.provenance.unknown
    : 0

  return (
    <section className="dev-page" aria-label="Developer window">
      <div className="dev-page__workspace">
        <aside className="dev-sidebar">
          <section className="dev-section">
            <div className="dev-state-summary">
              <article>
                <span>Backend</span>
                <StatePill active={state.api.ready}>{state.api.ready ? 'Ready' : 'Starting'}</StatePill>
              </article>
              <article><span>Project</span><strong title={projectName}>{projectName}</strong></article>
              <article>
                <span>Chunks</span>
                <strong>{stats ? stats.chunks.toLocaleString() : '—'}</strong>
              </article>
              <article>
                <span>Files</span>
                <strong>{stats ? stats.files.toLocaleString() : '—'}</strong>
              </article>
              <article title="Chunks whose CLAP vector was synthesized or predates the provenance column. Novelty is fiction for these.">
                <span>Untrusted vectors</span>
                <strong data-tone={untrusted > 0 ? 'warn' : 'good'}>
                  {stats ? untrusted.toLocaleString() : '—'}
                </strong>
              </article>
              <article title="Chunks with effectively no key evidence, where Fit's harmony term collapses to neutral.">
                <span>No key evidence</span>
                <strong data-tone={
                  stats && stats.key.absent > stats.chunks / 2 ? 'warn' : undefined
                }>
                  {stats ? stats.key.absent.toLocaleString() : '—'}
                </strong>
              </article>
              <article title="Chunks with no instrument assigned, where that term of Fit scores neutral whatever the preset.">
                <span>No instrument</span>
                <strong data-tone={stats && stats.roles.unassigned > 0 ? 'warn' : undefined}>
                  {stats ? stats.roles.unassigned.toLocaleString() : '—'}
                </strong>
              </article>
              <article><span>Folders</span><strong>{state.folders.length}</strong></article>
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

            <details className="dev-state-raw">
              <summary><span>Renderer internals</span><small>UI</small></summary>
              <dl className="dev-state-values">
                <div><dt>Gold Digger step</dt><dd>{goldDigger.currentStep}</dd></div>
                <div><dt>Ingest</dt><dd>{state.ingest.busy ? 'busy' : 'idle'}</dd></div>
                <div><dt>Visible panels</dt><dd>{goldDigger.visiblePanels.join(', ')}</dd></div>
                <div><dt>Leaving step</dt><dd>{goldDigger.leavingStep ?? '—'}</dd></div>
                <div><dt>Reached project</dt><dd>{String(goldDigger.hasReachedProject)}</dd></div>
                <div><dt>Jobs this session</dt><dd>{state.ingest.jobs.length}</dd></div>
                <div><dt>Ready jobs</dt><dd>{state.ingest.readyJobCount}</dd></div>
              </dl>
            </details>

            <details className="dev-state-raw">
              <summary><span>Raw state</span><small>JSON</small></summary>
              <pre>{JSON.stringify(snapshot, null, 2)}</pre>
            </details>
          </section>
        </aside>

        <section className="dev-inspector">
          <nav className="dev-tabs" aria-label="Developer data views">
            {(
              [
                ['corpus', 'Corpus'],
                ['presets', 'Presets'],
                ['files', 'Files'],
                ['context', 'Context']
              ] as [DevTab, string][]
            ).map(([id, label]) => (
              <button
                key={id}
                type="button"
                role="tab"
                aria-selected={activeTab === id}
                data-active={activeTab === id || undefined}
                onClick={() => setActiveTab(id)}
              >
                {label}
              </button>
            ))}
          </nav>
          <div className="dev-tab-panel" role="tabpanel">
            {activeTab === 'corpus' ? <CorpusTab /> : null}
            {activeTab === 'presets' ? (
              <PresetsTab project={state.project} activeRoots={state.activeFolderRoots} />
            ) : null}
            {activeTab === 'files' ? <AnalysisFilesTab application={state} /> : null}
            {activeTab === 'context' ? <ContextTab project={state.project} /> : null}
          </div>
        </section>
      </div>
    </section>
  )
}
