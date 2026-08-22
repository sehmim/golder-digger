/**
 * Ingest jobs as the UI sees them. Main polls Python and pushes every reading
 * here, so this hook only stitches those readings onto the rows it started.
 */
import { useCallback, useEffect, useState } from 'react'
import { baseName } from './api'
import type { JobStatus } from './api'

export interface IngestJob {
  jobId: string
  label: string
  state: 'queued' | 'running' | 'finished'
  total: number
  done: number
  failed: number
  currentFile: string | null
}

/** `total` is 0 until the walk finishes, so an unstarted job reads as 0. */
export function progressOf(job: IngestJob): number {
  return job.total > 0 ? Math.min(1, job.done / job.total) : 0
}

export function useIngest(): {
  jobs: IngestJob[]
  startIngest: (roots: string[], label?: string) => Promise<string>
  dismissJob: (jobId: string) => void
  clearJobs: () => void
  error: string | null
} {
  const [jobs, setJobs] = useState<IngestJob[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const offProgress = window.desktop.onIngestProgress((raw) => {
      const status = raw as JobStatus
      setJobs((current) =>
        current.map((job) =>
          job.jobId === status.job_id
            ? {
                ...job,
                state: status.state,
                total: status.total,
                done: status.done,
                failed: status.failed,
                currentFile: status.message
              }
            : job
        )
      )
    })

    const offError = window.desktop.onIngestError((payload) => {
      setError(String((payload as { error?: string }).error ?? 'ingest failed'))
    })

    return () => {
      offProgress()
      offError()
    }
  }, [])

  const startIngest = useCallback(async (roots: string[], label?: string) => {
    setError(null)
    const jobId = await window.desktop.startIngest(roots)

    setJobs((current) => [
      ...current,
      {
        jobId,
        label: label ?? baseName(roots[0]),
        state: 'queued',
        total: 0,
        done: 0,
        failed: 0,
        currentFile: null
      }
    ])

    return jobId
  }, [])

  // Python has no cancel, so dismissing only stops showing the row.
  const dismissJob = useCallback((jobId: string) => {
    setJobs((current) => current.filter((job) => job.jobId !== jobId))
  }, [])

  const clearJobs = useCallback(() => setJobs([]), [])

  return { jobs, startIngest, dismissJob, clearJobs, error }
}
