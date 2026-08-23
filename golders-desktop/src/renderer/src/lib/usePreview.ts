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

export interface PreviewSession {
  /** Session tempo. Candidates are time-stretched to it; pitch is untouched. */
  bpm?: number | null
  /** The session's own chunks, mixed underneath the candidate. */
  contextIds?: string[]
}

export interface Preview {
  /** The chunk currently sounding, if any. */
  playing: string | null
  /** The chunk whose audio is still being rendered. */
  loading: string | null
  error: string | null
  toggle: (chunkId: string) => void
  /** True when candidates play alone rather than over the session. */
  candidateOnly: boolean
  setCandidateOnly: (value: boolean) => void
}

export function usePreview(session: PreviewSession = {}): Preview {
  const [playing, setPlaying] = useState<string | null>(null)
  const [loading, setLoading] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [candidateOnly, setCandidateOnly] = useState(false)

  const element = useRef<HTMLAudioElement | null>(null)
  const urls = useRef(new Map<string, string>())
  // A slow render must not start playing after the user has moved on.
  const wanted = useRef<string | null>(null)

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

    const stop = (): void => setPlaying(null)
    audio.addEventListener('ended', stop)

    return () => {
      audio.removeEventListener('ended', stop)
      audio.pause()
      for (const url of urls.current.values()) URL.revokeObjectURL(url)
      urls.current.clear()
    }
  }, [])

  // Changing tempo or the solo/in-context switch invalidates every rendered blob.
  useEffect(() => {
    const audio = element.current
    audio?.pause()
    wanted.current = null
    setPlaying(null)
    for (const url of urls.current.values()) URL.revokeObjectURL(url)
    urls.current.clear()
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
      wanted.current = chunkId
      setError(null)

      const play = (url: string): void => {
        if (wanted.current !== chunkId) return
        audio.src = url
        void audio
          .play()
          .then(() => setPlaying(chunkId))
          .catch((cause) => {
            setError(String(cause instanceof Error ? cause.message : cause))
          })
      }

      const cacheKey = `${chunkId}@${renderKey}`
      const cached = urls.current.get(cacheKey)
      if (cached) {
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
          const url = URL.createObjectURL(new Blob([bytes], { type: 'audio/wav' }))
          urls.current.set(cacheKey, url)
          play(url)
        })
        .catch((cause) => setError(String(cause instanceof Error ? cause.message : cause)))
        .finally(() => setLoading((current) => (current === chunkId ? null : current)))
    },
    [playing, renderKey, bpm, candidateOnly, session.contextIds]
  )

  return { playing, loading, error, toggle, candidateOnly, setCandidateOnly }
}
