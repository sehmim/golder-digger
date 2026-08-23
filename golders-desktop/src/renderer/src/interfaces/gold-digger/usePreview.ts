/**
 * Audition one chunk at a time, in time with the session.
 *
 * The API renders to WAV on demand, so bytes arrive over IPC and become a blob
 * URL here. Blobs are cached: moving the DISTANCE dial back and forth re-lists
 * the same candidates, and re-rendering audio for each pass would cost a librosa
 * decode every time.
 *
 * The cache is keyed on the *render*, not the chunk. A candidate stretched to
 * 120 BPM and the same candidate stretched to 90 are different audio, and
 * hearing it alone is different again from hearing it over the session -- keying
 * on chunk id alone would silently replay whichever one happened to be fetched
 * first, which is exactly the kind of bug you cannot hear is a bug.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

const PREVIEW_CACHE_LIMIT = 48

export interface PreviewSession {
  /** Session tempo. Candidates are time-stretched to it; pitch is untouched. */
  bpm?: number | null
  /** The session's own chunks, mixed underneath the candidate. */
  contextIds?: string[]
  /**
   * Start with the candidate alone rather than over the session.
   *
   * The stepped flow opens on the mix because judging the *combination* is its
   * whole purpose and the step says so. A bare results list has no such framing:
   * clicking a sample there and hearing the entire project underneath it reads
   * as the wrong file playing, not as a considered default.
   */
  soloFirst?: boolean
}

export interface Preview {
  /** The chunk currently sounding, if any. */
  playing: string | null
  /** The chunk whose audio is still being rendered. */
  loading: string | null
  error: string | null
  toggle: (chunkId: string) => void
  /** How far through the sounding chunk, 0-1. Zero when nothing is playing. */
  progress: number
  /** Jump within the sounding chunk. Ignored while nothing is playing. */
  seek: (fraction: number) => void
  /** True when candidates play alone rather than over the session. */
  candidateOnly: boolean
  setCandidateOnly: (value: boolean) => void
}

export function usePreview(session: PreviewSession = {}): Preview {
  const [playing, setPlaying] = useState<string | null>(null)
  const [loading, setLoading] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [candidateOnly, setCandidateOnly] = useState(session.soloFirst ?? false)
  const [progress, setProgress] = useState(0)

  const element = useRef<HTMLAudioElement | null>(null)
  const urls = useRef(new Map<string, string>())
  // A slow render must not start playing after the user has moved on.
  const wanted = useRef<string | null>(null)
  const alive = useRef(true)

  const bpm = session.bpm ?? null
  const contextKey = (session.contextIds ?? []).join(',')

  /** Everything that changes the rendered bytes, so the cache cannot serve a stale mix. */
  const renderKey = useMemo(
    () => `${bpm ?? 'as-is'}|${candidateOnly ? 'solo' : contextKey}`,
    [bpm, candidateOnly, contextKey]
  )

  if (element.current === null && typeof Audio !== 'undefined') {
    element.current = new Audio()
  }

  useEffect(() => {
    const audio = element.current
    if (!audio) return
    // React StrictMode mounts this effect twice in development.
    alive.current = true

    const stop = (): void => {
      setPlaying(null)
      setProgress(0)
    }
    // `timeupdate` rather than rAF: it fires often enough for a playhead and
    // stops on its own when the element pauses, so nothing has to be cancelled.
    const tick = (): void => {
      setProgress(audio.duration > 0 ? audio.currentTime / audio.duration : 0)
    }
    audio.addEventListener('ended', stop)
    audio.addEventListener('timeupdate', tick)

    return () => {
      alive.current = false
      wanted.current = null
      audio.removeEventListener('ended', stop)
      audio.removeEventListener('timeupdate', tick)
      audio.pause()
      for (const url of urls.current.values()) URL.revokeObjectURL(url)
      urls.current.clear()
    }
  }, [])

  // Stop on a mode change, but keep mode-specific blobs: renderKey already keeps
  // solo and in-context audio separate, so toggling back should be instant.
  useEffect(() => {
    const audio = element.current
    audio?.pause()
    wanted.current = null
    setPlaying(null)
    setProgress(0)
  }, [renderKey])

  const toggle = useCallback(
    (chunkId: string) => {
      const audio = element.current
      if (!audio) return

      if (playing === chunkId) {
        audio.pause()
        wanted.current = null
        setPlaying(null)
        return
      }

      audio.pause()
      setError(null)
      setProgress(0)

      const cacheKey = `${chunkId}@${renderKey}`
      wanted.current = cacheKey

      const play = (url: string): void => {
        if (wanted.current !== cacheKey) return
        audio.src = url
        void audio
          .play()
          .then(() => setPlaying(chunkId))
          .catch((cause) => {
            setError(String(cause instanceof Error ? cause.message : cause))
          })
      }

      const cached = urls.current.get(cacheKey)
      if (cached) {
        // Refresh insertion order so the Map doubles as a tiny LRU.
        urls.current.delete(cacheKey)
        urls.current.set(cacheKey, cached)
        play(cached)
        return
      }

      setLoading(chunkId)
      void window.desktop
        .chunkAudio(chunkId, {
          bpm,
          contextIds: candidateOnly ? [] : session.contextIds,
          candidateOnly
        })
        .then((bytes) => {
          if (!alive.current) return
          const url = URL.createObjectURL(new Blob([bytes], { type: 'audio/wav' }))
          urls.current.set(cacheKey, url)
          while (urls.current.size > PREVIEW_CACHE_LIMIT) {
            const oldest = urls.current.entries().next().value as [string, string] | undefined
            if (!oldest) break
            urls.current.delete(oldest[0])
            URL.revokeObjectURL(oldest[1])
          }
          play(url)
        })
        .catch((cause) => {
          if (wanted.current === cacheKey) {
            setError(String(cause instanceof Error ? cause.message : cause))
          }
        })
        .finally(() => {
          if (wanted.current === cacheKey) setLoading(null)
        })
    },
    [playing, renderKey, bpm, candidateOnly, session.contextIds]
  )

  const seek = useCallback((fraction: number) => {
    const audio = element.current
    if (!audio || !(audio.duration > 0)) return
    const target = Math.min(1, Math.max(0, fraction))
    audio.currentTime = target * audio.duration
    setProgress(target)
  }, [])

  return { playing, loading, error, toggle, progress, seek, candidateOnly, setCandidateOnly }
}
