import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useApplication } from '../../application/ApplicationState'
import DigStep from './steps/DigStep'
import ProjectStep from './steps/ProjectStep'
import SourcesStep from './steps/SourcesStep'
import type { GoldDiggerDiagnostics, GoldDiggerStep } from './types'

const ORDER: GoldDiggerStep[] = ['sources', 'project', 'dig']
const ADVANCE_DELAY_MS = 520
const ADVANCE_DURATION_MS = 700

interface GoldDiggerAppProps {
  onDiagnosticsChange: (diagnostics: GoldDiggerDiagnostics) => void
}

export default function GoldDiggerApp({
  onDiagnosticsChange
}: GoldDiggerAppProps): React.JSX.Element {
  const { state, actions } = useApplication()
  const [step, setStep] = useState<GoldDiggerStep>('sources')
  const [leaving, setLeaving] = useState<GoldDiggerStep | null>(null)
  const [hasReachedProject, setHasReachedProject] = useState(false)
  const hasAdvanced = useRef(false)
  const handoff = useRef<ReturnType<typeof setTimeout> | null>(null)

  const readyJobs = state.ingest.jobs.filter(
    (job) => job.kind === 'ingest' && job.state === 'finished'
  )
  const shown = useMemo(
    () => ORDER.filter((candidate) => candidate === step || candidate === leaving),
    [leaving, step]
  )

  const diagnostics = useMemo<GoldDiggerDiagnostics>(
    () => ({
      currentStep: step,
      leavingStep: leaving,
      visiblePanels: shown,
      hasReachedProject
    }),
    [hasReachedProject, leaving, shown, step]
  )

  useEffect(() => onDiagnosticsChange(diagnostics), [diagnostics, onDiagnosticsChange])

  const goTo = useCallback((next: GoldDiggerStep) => {
    setStep((current) => {
      if (current === next) return current
      setLeaving(current)
      if (handoff.current) clearTimeout(handoff.current)
      handoff.current = setTimeout(() => setLeaving(null), ADVANCE_DURATION_MS)
      return next
    })
  }, [])

  useEffect(
    () => () => {
      if (handoff.current) clearTimeout(handoff.current)
    },
    []
  )

  useEffect(() => {
    if (hasAdvanced.current || readyJobs.length === 0 || state.ingest.busy) return

    hasAdvanced.current = true
    setHasReachedProject(true)
    const start = setTimeout(() => goTo('project'), ADVANCE_DELAY_MS)
    return () => clearTimeout(start)
  }, [goTo, readyJobs.length, state.ingest.busy])

  function clearAll(): void {
    hasAdvanced.current = false
    setHasReachedProject(false)
    actions.clearJobs()
  }

  function panelClass(candidate: GoldDiggerStep): string {
    if (candidate === leaving) return 'panel panel--leaving'
    return leaving ? 'panel panel--entering' : 'panel'
  }

  return (
    <main className="page" aria-label="Gold Digger App">
      <div className="stage" data-step={step}>
        {shown.map((candidate) => (
          <div key={candidate} className={panelClass(candidate)}>
            {candidate === 'sources' ? (
              <SourcesStep
                jobs={state.ingest.jobs}
                apiReady={state.api.ready}
                canContinue={hasReachedProject && readyJobs.length > 0 && !state.ingest.busy}
                onChoose={() => void actions.chooseDirectories()}
                onDismiss={actions.dismissJob}
                onClear={clearAll}
                onContinue={() => goTo('project')}
                onRunEssentia={(roots) => void actions.runEssentia(roots)}
              />
            ) : null}

            {candidate === 'project' ? (
              <ProjectStep
                ingestJobs={state.ingest.jobs}
                startIngest={actions.startIngest}
                sourceCount={readyJobs.length}
                onBack={() => goTo('sources')}
                dugSet={state.project}
                onDig={(project) => {
                  actions.setProject(project)
                  goTo('dig')
                }}
              />
            ) : null}

            {candidate === 'dig' && state.project ? (
              <DigStep
                set={state.project}
                activeRoots={state.activeFolderRoots}
                onBack={() => goTo('project')}
              />
            ) : null}
          </div>
        ))}
      </div>

      {state.api.error ? <p className="error banner">{state.api.error}</p> : null}
      {state.ingest.error ? <p className="error banner">{state.ingest.error}</p> : null}
    </main>
  )
}
