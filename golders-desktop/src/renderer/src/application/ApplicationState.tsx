import { createContext, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import type { ApiStatus, SessionSet } from './api'
import { useIngest } from './useIngest'
import type { IngestJob } from './useIngest'

export type KnobStyle = 'classic' | 'dark' | 'minimal'

export interface ApplicationState {
  api: ApiStatus
  /** Directory roots currently represented by tracked ingest jobs. */
  directories: string[]
  ingest: {
    jobs: IngestJob[]
    readyJobCount: number
    busy: boolean
    error: string | null
  }
  project: SessionSet | null
  settings: {
    knobStyle: KnobStyle
  }
}

export interface ApplicationActions {
  chooseDirectories: () => Promise<void>
  startIngest: (roots: string[], label?: string) => Promise<string>
  runEssentia: (roots: string[]) => Promise<void>
  dismissJob: (jobId: string) => void
  clearJobs: () => void
  setProject: (project: SessionSet | null) => void
  setKnobStyle: (style: KnobStyle) => void
}

interface ApplicationContextValue {
  state: ApplicationState
  actions: ApplicationActions
}

const ApplicationContext = createContext<ApplicationContextValue | null>(null)

export function ApplicationStateProvider({ children }: { children: ReactNode }): React.JSX.Element {
  const { jobs, startIngest, startEssentia, dismissJob, clearJobs, error } = useIngest()
  const [api, setApi] = useState<ApiStatus>({ ready: false, error: null })
  const [project, setProject] = useState<SessionSet | null>(null)
  const [knobStyle, setKnobStyle] = useState<KnobStyle>('classic')

  useEffect(() => {
    const off = window.desktop.onApiReady((status) => setApi(status as ApiStatus))
    void window.desktop.apiStatus().then(setApi)
    return off
  }, [])

  const value = useMemo<ApplicationContextValue>(() => {
    const readyJobCount = jobs.filter(
      (job) => job.kind === 'ingest' && job.state === 'finished'
    ).length
    const directories = [
      ...new Set(jobs.filter((job) => job.kind === 'ingest').flatMap((job) => job.roots))
    ]

    return {
      state: {
        api,
        directories,
        ingest: {
          jobs,
          readyJobCount,
          busy: jobs.some((job) => job.state !== 'finished'),
          error
        },
        project,
        settings: { knobStyle }
      },
      actions: {
        chooseDirectories: async () => {
          const selected = await window.desktop.selectDirectories()
          for (const directory of selected) await startIngest([directory])
        },
        startIngest,
        runEssentia: async (roots) => {
          for (const root of roots) await startEssentia(root)
        },
        dismissJob,
        clearJobs,
        setProject,
        setKnobStyle
      }
    }
  }, [api, clearJobs, dismissJob, error, jobs, knobStyle, project, startEssentia, startIngest])

  return <ApplicationContext.Provider value={value}>{children}</ApplicationContext.Provider>
}

export function useApplication(): ApplicationContextValue {
  const value = useContext(ApplicationContext)
  if (!value) throw new Error('useApplication must be used inside ApplicationStateProvider')
  return value
}
