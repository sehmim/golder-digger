import { useCallback, useEffect, useRef, useState } from 'react'
import { useApplication } from '../../application/ApplicationState'
import InterfaceMenu from '../../shared/components/InterfaceMenu'
import type { InterfaceId } from '../../shared/interfaceNavigation'
import { usePreview } from '../gold-digger/usePreview'
import FolderStrip from './FolderStrip'
import GoldenKnob from './GoldenKnob'
import GoldenResults from './GoldenResults'
import type { GoldenResultsState } from './GoldenResults'

const RESULT_COUNT = 30

interface GoldenAppProps {
  onNavigate: (destination: InterfaceId) => void
  onOpenFolderManager: (folderId?: string) => void
}

function tonalCenter(key: string | null): string | null {
  return key?.match(/^[A-G](?:#|b)?/)?.[0] ?? null
}

export default function GoldenApp({
  onNavigate,
  onOpenFolderManager
}: GoldenAppProps): React.JSX.Element {
  const { state, actions } = useApplication()
  const [value, setValue] = useState(50)
  const [results, setResults] = useState<GoldenResultsState>({ status: 'idle' })
  const [contextLoading, setContextLoading] = useState(false)
  const [contextError, setContextError] = useState<string | null>(null)
  const [jobId, setJobId] = useState<string | null>(null)
  // One automatic ingest per set. Without this the effect below would restart
  // the job every time its own reload produced a set that still had gaps --
  // a project referencing audio that cannot be read would loop forever.
  const autoIngested = useRef(new Set<string>())
  const requestGeneration = useRef(0)

  const project = state.project
  const tempo = project?.session.tempo ?? null
  const center = tonalCenter(project?.session.key ?? null)
  const hasUsableContext = Boolean(project && project.context_ids.length > 0)
  const job = state.ingest.jobs.find((candidate) => candidate.jobId === jobId) ?? null
  // Samples the set references that are on disk but absent from the corpus.
  // These are the reason a project can load perfectly and still rank nothing.
  const missing = project?.unmatched.filter((sample) => sample.ingest_path).length ?? 0
  // Candidates are auditioned against this set, so previews are stretched to its
  // tempo and mixed over its own chunks -- the same contract the stepped flow uses.
  const preview = usePreview({
    bpm: project?.session.tempo ?? null,
    contextIds: project?.context_ids,
    soloFirst: true
  })

  const load = useCallback(
    async (path: string) => {
      setContextLoading(true)
      setContextError(null)
      try {
        actions.setProject(await window.desktop.loadSet(path))
      } catch (cause) {
        setContextError(cause instanceof Error ? cause.message : String(cause))
      } finally {
        setContextLoading(false)
      }
    },
    [actions]
  )

  async function chooseContext(): Promise<void> {
    const path = await window.desktop.selectProject()
    if (!path) return
    autoIngested.current.delete(path)
    await load(path)
  }

  // A set whose samples were never ingested resolves to zero context chunks, and
  // the knob is then correctly disabled -- but that used to be the whole story
  // the UI told: a project that had plainly loaded, next to a dial that did
  // nothing. Analyse what it references, the way the stepped flow already does.
  useEffect(() => {
    if (!project || job || contextLoading) return
    const path = project.session.path
    if (missing === 0 || autoIngested.current.has(path)) return

    autoIngested.current.add(path)
    const paths = project.unmatched
      .map((sample) => sample.ingest_path)
      .filter((value): value is string => Boolean(value))

    void actions
      .startIngest(paths, `${paths.length} ${paths.length === 1 ? 'sample' : 'samples'}`)
      .then(setJobId)
      .catch((cause) => setContextError(cause instanceof Error ? cause.message : String(cause)))
  }, [project, job, contextLoading, missing, actions])

  // Resolve again once those samples exist: the same set now matches them.
  useEffect(() => {
    if (!project || job?.state !== 'finished') return
    setJobId(null)
    void load(project.session.path)
  }, [job?.state, project, load])

  /** The line under the project name. It has to explain a dead knob. */
  function contextMeta(): string {
    if (contextLoading) return 'Reading…'
    if (contextError) return contextError
    if (job) {
      const done = job.total > 0 ? ` ${job.done}/${job.total}` : ''
      return `Analyzing ${job.label}${done}…`
    }
    if (project && !hasUsableContext) {
      return missing > 0
        ? `${missing} of its samples are not analyzed yet`
        : 'None of this project’s audio is in your library'
    }
    const summary = [tempo === null ? null : `${Math.round(tempo)} BPM`, center]
      .filter(Boolean)
      .join(' · ')
    return summary || 'Context'
  }

  function rank(distance: number): void {
    if (!project) {
      void chooseContext()
      return
    }

    if (project.context_ids.length === 0) {
      setResults({
        status: 'error',
        distance,
        message: 'This project has no resolved audio to use as context.'
      })
      return
    }

    const generation = ++requestGeneration.current
    setResults({ status: 'loading', distance })
    void window.desktop
      .analyze(
        project.context_ids,
        distance,
        RESULT_COUNT,
        project.session.path,
        state.activeFolderRoots
      )
      .then((result) => {
        if (requestGeneration.current === generation) {
          setResults({ status: 'ready', distance, result })
        }
      })
      .catch((cause) => {
        if (requestGeneration.current === generation) {
          setResults({
            status: 'error',
            distance,
            message: cause instanceof Error ? cause.message : String(cause)
          })
        }
      })
  }

  function returnToKnob(): void {
    requestGeneration.current += 1
    setResults({ status: 'idle' })
  }

  return (
    <main className="golden-page" aria-label="Golden UI">
      <button
        type="button"
        className="golden-context-trigger"
        data-error={contextError || undefined}
        onClick={() => void chooseContext()}
        title={contextError ?? project?.session.path}
        disabled={contextLoading || Boolean(job)}
      >
        {project ? (
          <>
            <span className="golden-context-trigger__name">{project.session.name}</span>
            <span className="golden-context-trigger__meta">{contextMeta()}</span>
          </>
        ) : (
          <>
            <span className="golden-context-trigger__name">No Ableton project</span>
            <span className="golden-context-trigger__meta">
              {contextLoading ? 'Reading…' : contextError ?? '+ Choose .als'}
            </span>
          </>
        )}
      </button>
      <div className="golden-page__controls">
        <FolderStrip folders={state.folders} onOpenManager={onOpenFolderManager} />
        <InterfaceMenu current="golden" onNavigate={onNavigate} />
      </div>
      <GoldenKnob
        value={value}
        onChange={setValue}
        onCommit={rank}
        style={state.settings.knobStyle}
        disabled={!hasUsableContext || contextLoading || Boolean(job)}
      />
      {results.status !== 'idle' ? <GoldenResults
          state={results}
          preview={preview}
          sessionBpm={project?.session.tempo ?? null}
          onBack={returnToKnob}
        /> : null}
    </main>
  )
}
