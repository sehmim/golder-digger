import { useEffect, useRef, useState } from 'react'
import { useIngest } from './lib/useIngest'
import type { ApiStatus } from './lib/api'
import SourcesStep from './steps/SourcesStep'
import ProjectStep from './steps/ProjectStep'

type Phase = 'sources' | 'advancing' | 'project'

const ADVANCE_DELAY_MS = 520
const ADVANCE_DURATION_MS = 700

const STEPS = ['Samples', 'Project'] as const

export default function App(): React.JSX.Element {
  const { jobs, startIngest, dismissJob, clearJobs, error } = useIngest()
  const [phase, setPhase] = useState<Phase>('sources')
  const [hasReachedProject, setHasReachedProject] = useState(false)
  const [api, setApi] = useState<ApiStatus>({ ready: false, error: null })
  const hasAdvanced = useRef(false)

  const readyJobs = jobs.filter((job) => job.state === 'finished')

  // Python boots after the window paints, so its readiness arrives either way.
  useEffect(() => {
    const off = window.desktop.onApiReady((status) => setApi(status as ApiStatus))
    void window.desktop.apiStatus().then(setApi)
    return off
  }, [])

  // The first folder to finish ingesting hands the screen over to the project step.
  useEffect(() => {
    if (hasAdvanced.current || readyJobs.length === 0) return

    hasAdvanced.current = true
    setHasReachedProject(true)
    const start = setTimeout(() => setPhase('advancing'), ADVANCE_DELAY_MS)
    return () => clearTimeout(start)
  }, [readyJobs.length])

  useEffect(() => {
    if (phase !== 'advancing') return

    const finish = setTimeout(() => setPhase('project'), ADVANCE_DURATION_MS)
    return () => clearTimeout(finish)
  }, [phase])

  async function chooseDirectories(): Promise<void> {
    const directories = await window.desktop.selectDirectories()
    // One job per folder, so each gets its own row and its own progress.
    for (const directory of directories) await startIngest([directory])
  }

  function clearAll(): void {
    hasAdvanced.current = false
    setHasReachedProject(false)
    clearJobs()
  }

  const stepIndex = phase === 'sources' ? 0 : 1

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

      <div className="stage" data-phase={phase}>
        {phase !== 'project' ? (
          <div className={`panel${phase === 'advancing' ? ' panel--leaving' : ''}`}>
            <SourcesStep
              jobs={jobs}
              apiReady={api.ready}
              canContinue={hasReachedProject && readyJobs.length > 0}
              onChoose={() => void chooseDirectories()}
              onDismiss={dismissJob}
              onClear={clearAll}
              onContinue={() => setPhase('project')}
            />
          </div>
        ) : null}

        {phase !== 'sources' ? (
          <div className={`panel${phase === 'advancing' ? ' panel--entering' : ''}`}>
            <ProjectStep
              ingestJobs={jobs}
              startIngest={startIngest}
              sourceCount={readyJobs.length}
              onBack={() => setPhase('sources')}
            />
          </div>
        ) : null}
      </div>

      {api.error ? <p className="error banner">{api.error}</p> : null}
      {error ? <p className="error banner">{error}</p> : null}
    </main>
  )
}
