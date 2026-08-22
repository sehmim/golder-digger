/**
 * Audition one chunk at a time.
 *
 * The API renders a chunk to WAV on demand, so bytes arrive over IPC and become
 * a blob URL here. Blobs are cached per chunk: moving the DISTANCE dial back and
 * forth re-lists the same candidates, and re-rendering audio for each pass would
 * cost a librosa decode every time.
 */
import { useCallback, useEffect, useRef, useState } from 'react'

export interface Preview {
  /** The chunk currently sounding, if any. */
  playing: string | null
  /** The chunk whose audio is still being rendered. */
  loading: string | null
  error: string | null
  toggle: (chunkId: string) => void
}

export function usePreview(): Preview {
  const [playing, setPlaying] = useState<string | null>(null)
  const [loading, setLoading] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const element = useRef<HTMLAudioElement | null>(null)
  const urls = useRef(new Map<string, string>())
  // A slow render must not start playing after the user has moved on.
  const wanted = useRef<string | null>(null)

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

  const toggle = useCallback((chunkId: string) => {
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
      void audio.play().then(() => setPlaying(chunkId)).catch((cause) => {
        setError(String(cause instanceof Error ? cause.message : cause))
      })
    }

    const cached = urls.current.get(chunkId)
    if (cached) {
      play(cached)
      return
    }

    setLoading(chunkId)
    void window.desktop
      .chunkAudio(chunkId)
      .then((bytes) => {
        const url = URL.createObjectURL(new Blob([bytes], { type: 'audio/wav' }))
        urls.current.set(chunkId, url)
        play(url)
      })
      .catch((cause) => setError(String(cause instanceof Error ? cause.message : cause)))
      .finally(() => setLoading((current) => (current === chunkId ? null : current)))
  }, [playing])

  return { playing, loading, error, toggle }
}
