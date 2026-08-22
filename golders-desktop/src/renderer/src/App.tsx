import { useCallback, useEffect, useRef, useState } from 'react'
import { useIngest } from './lib/useIngest'
import type { ApiStatus, SessionSet } from './lib/api'
import SourcesStep from './steps/SourcesStep'
import ProjectStep from './steps/ProjectStep'
import DigStep from './steps/DigStep'

type Step = 'sources' | 'project' | 'dig'

const ORDER: Step[] = ['sources', 'project', 'dig']
const STEPS = ['Samples', 'Project', 'Dig'] as const

const ADVANCE_DELAY_MS = 520
const ADVANCE_DURATION_MS = 700

export default function App(): React.JSX.Element {
  const { jobs, startIngest, startEssentia, dismissJob, clearJobs, error } = useIngest()
  const [step, setStep] = useState<Step>('sources')
  // The step on its way out, kept mounted for the length of the handoff.
  const [leaving, setLeaving] = useState<Step | null>(null)
  const [set, setSet] = useState<SessionSet | null>(null)
  const [hasReachedProject, setHasReachedProject] = useState(false)
  const [api, setApi] = useState<ApiStatus>({ ready: false, error: null })

  const hasAdvanced = useRef(false)
  const handoff = useRef<ReturnType<typeof setTimeout> | null>(null)

  const readyJobs = jobs.filter((job) => job.kind === 'ingest' && job.state === 'finished')
  // Ingest now runs Essentia per file, so a folder is only characterised when its
  // job says finished. Any job still moving keeps the screen where it is.
  const busy = jobs.some((job) => job.state !== 'finished')

  const goTo = useCallback((next: Step) => {
    setStep((current) => {
      if (current === next) return current
      setLeaving(current)
      if (handoff.current) clearTimeout(handoff.current)
      handoff.current = setTimeout(() => setLeaving(null), ADVANCE_DURATION_MS)
      return next
    })
  }, [])

  // Python boots after the window paints, so its readiness arrives either way.
  useEffect(() => {
    const off = window.desktop.onApiReady((status) => setApi(status as ApiStatus))
    void window.desktop.apiStatus().then(setApi)
    return off
  }, [])

  // The first folder to finish ingesting hands the screen over to the project step.
  useEffect(() => {
    if (hasAdvanced.current || readyJobs.length === 0 || busy) return

    hasAdvanced.current = true
    setHasReachedProject(true)
    const start = setTimeout(() => goTo('project'), ADVANCE_DELAY_MS)
    return () => clearTimeout(start)
  }, [readyJobs.length, busy, goTo])

  async function chooseDirectories(): Promise<void> {
    const directories = await window.desktop.selectDirectories()
    // One job per folder, so each gets its own row and its own progress.
    for (const directory of directories) await startIngest([directory])
  }

  async function runEssentia(roots: string[]): Promise<void> {
    // One pass per folder: the extractor takes a directory, not a list.
    for (const root of roots) await startEssentia(root)
  }

  function clearAll(): void {
    hasAdvanced.current = false
    setHasReachedProject(false)
    clearJobs()
  }

  function panelClass(candidate: Step): string {
    if (candidate === leaving) return 'panel panel--leaving'
    return leaving ? 'panel panel--entering' : 'panel'
  }

  const stepIndex = ORDER.indexOf(step)
  const shown = ORDER.filter((candidate) => candidate === step || candidate === leaving)

  return (
    <main className="page">
      <nav className="steps" aria-label="Setup progress">
        {STEPS.map((label, index) => (
          <span
            key={label}
            className="step"
            data-state={index < stepIndex ? 'done' : index === stepIndex ? 'active' : 'waiting'}
          >
            <span className="step-dot" aria-hidden="true" />
            {label}
          </span>
        ))}
      </nav>

      <div className="stage" data-step={step}>
        {shown.map((candidate) => (
          <div key={candidate} className={panelClass(candidate)}>
            {candidate === 'sources' ? (
              <SourcesStep
                jobs={jobs}
                apiReady={api.ready}
                canContinue={hasReachedProject && readyJobs.length > 0 && !busy}
                onChoose={() => void chooseDirectories()}
                onDismiss={dismissJob}
                onClear={clearAll}
                onContinue={() => goTo('project')}
                onRunEssentia={(roots) => void runEssentia(roots)}
              />
            ) : null}

            {candidate === 'project' ? (
              <ProjectStep
                ingestJobs={jobs}
                startIngest={startIngest}
                sourceCount={readyJobs.length}
                onBack={() => goTo('sources')}
                onDig={(connected) => {
                  setSet(connected)
                  goTo('dig')
                }}
              />
            ) : null}

            {candidate === 'dig' && set ? (
              <DigStep set={set} onBack={() => goTo('project')} />
            ) : null}
          </div>
        ))}
      </div>

      {api.error ? <p className="error banner">{api.error}</p> : null}
      {error ? <p className="error banner">{error}</p> : null}
    </main>
  )
}
