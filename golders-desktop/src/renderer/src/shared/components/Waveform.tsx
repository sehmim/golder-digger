/**
 * A SoundCloud-style waveform for one chunk: click to play, click again to seek,
 * drag out to Ableton.
 *
 * Peaks come from the API rather than from decoding the audio here. The renderer
 * would otherwise have to fetch and decode every result's audio just to draw a
 * shape -- thirty librosa renders for a list nobody has clicked yet. The peaks
 * route is a few hundred bytes and warms the same render cache the playback then
 * hits, so drawing a waveform makes the first play faster rather than slower.
 *
 * Drawn as one SVG path per side rather than a canvas: the list re-renders on
 * every DISTANCE move, and a canvas would need redrawing imperatively on each
 * pass while an SVG path is just markup React can leave alone.
 */
import { useEffect, useRef, useState } from 'react'
import type { ChunkPeaks } from '../../application/api'

const BUCKETS = 200
const HEIGHT = 40

/** Peaks are shared across every list showing the same chunk at the same tempo.
 *  Keyed by tempo too: a chunk stretched to 120 and the same chunk at 90 are
 *  different audio and different shapes. */
const cache = new Map<string, ChunkPeaks>()
const inflight = new Map<string, Promise<ChunkPeaks>>()

function loadPeaks(chunkId: string, bpm: number | null): Promise<ChunkPeaks> {
  const key = `${chunkId}@${bpm ?? 'as-is'}`
  const cached = cache.get(key)
  if (cached) return Promise.resolve(cached)
  const running = inflight.get(key)
  if (running) return running

  const request = window.desktop
    .chunkPeaks(chunkId, BUCKETS, bpm)
    .then((data) => {
      cache.set(key, data)
      return data
    })
    .finally(() => inflight.delete(key))
  inflight.set(key, request)
  return request
}

/** `Kick_Loop.wav` + bar 3 + 128 BPM -> `Kick_Loop__bar3_128bpm.wav`. */
export function dragFileName(path: string, chunkId: string, bpm: number | null): string {
  const base = (path.split('/').pop() ?? 'sample').replace(/\.[^.]+$/, '')
  const index = Number(chunkId.split(':')[1] ?? 0)
  // Only label the slice when there is one: a one-shot is the whole file, and
  // "__bar1" on it would claim a structure the file does not have.
  const slice = index > 0 ? `__bar${index * 4 + 1}` : ''
  const tempo = bpm ? `_${Math.round(bpm)}bpm` : ''
  return `${base}${slice}${tempo}.wav`
}

interface WaveformProps {
  chunkId: string
  path: string
  /** The chunk's own tempo. Names the dragged file; never stretches it. */
  bpm: number | null
  /** Session tempo. The shape is rendered to it, because playback is. */
  sessionBpm?: number | null
  playing: boolean
  loading: boolean
  /** 0-1 through the sounding chunk. Only meaningful while `playing`. */
  progress: number
  onToggle: () => void
  onSeek: (fraction: number) => void
}

export default function Waveform({
  chunkId,
  path,
  bpm,
  sessionBpm = null,
  playing,
  loading,
  progress,
  onToggle,
  onSeek
}: WaveformProps): React.JSX.Element {
  const peakKey = `${chunkId}@${sessionBpm ?? 'as-is'}`
  const [peaks, setPeaks] = useState<ChunkPeaks | null>(cache.get(peakKey) ?? null)
  const host = useRef<HTMLDivElement | null>(null)
  const dragFile = useRef<string | null>(null)

  useEffect(() => {
    let cancelled = false
    const cached = cache.get(peakKey)
    if (cached) {
      setPeaks(cached)
      return
    }
    setPeaks(null)
    // Only draw once it is on screen: a thirty-result list would otherwise ask
    // for thirty renders the moment the dial moves.
    const node = host.current
    if (!node || typeof IntersectionObserver === 'undefined') {
      void loadPeaks(chunkId, sessionBpm).then((data) => !cancelled && setPeaks(data))
      return
    }
    const observer = new IntersectionObserver((entries) => {
      if (!entries.some((entry) => entry.isIntersecting)) return
      observer.disconnect()
      void loadPeaks(chunkId, sessionBpm).then((data) => !cancelled && setPeaks(data))
    })
    observer.observe(node)
    return () => {
      cancelled = true
      observer.disconnect()
    }
  }, [chunkId, peakKey, sessionBpm])

  /** Where in the waveform a pointer landed, 0-1. */
  function fractionAt(event: React.MouseEvent<HTMLDivElement>): number {
    const box = event.currentTarget.getBoundingClientRect()
    return box.width > 0 ? (event.clientX - box.left) / box.width : 0
  }

  // The temp WAV must exist before startDrag runs, and awaiting a render inside
  // dragstart loses the gesture -- so it is written on pointer-down.
  function prepare(): void {
    if (dragFile.current) return
    void window.desktop
      .prepareChunkDrag(chunkId, dragFileName(path, chunkId, bpm))
      .then((file) => {
        dragFile.current = file
      })
      .catch(() => undefined)
  }

  const mid = HEIGHT / 2
  const shape = peaks
    ? peaks.peaks
        .map(([low, high], i) => {
          const x = (i / peaks.peaks.length) * 100
          const top = mid - Math.min(1, Math.abs(high)) * mid
          const bottom = mid + Math.min(1, Math.abs(low)) * mid
          return `M${x.toFixed(3)} ${top.toFixed(2)}V${bottom.toFixed(2)}`
        })
        .join('')
    : ''

  return (
    <div
      ref={host}
      className="waveform"
      data-playing={playing || undefined}
      data-loading={loading || undefined}
      role="button"
      tabIndex={0}
      draggable
      title={`${playing ? 'Pause' : 'Play'} · drag into Ableton`}
      aria-label={`${playing ? 'Pause' : 'Play'} ${path.split('/').pop() ?? chunkId}`}
      onMouseDown={prepare}
      onDragStart={(event) => {
        // Electron replaces the drag with a real file drag; without a payload
        // here some targets reject the gesture before that happens.
        event.dataTransfer.effectAllowed = 'copy'
        if (dragFile.current) {
          window.desktop.startChunkDrag(dragFile.current)
        } else {
          // Not rendered yet -- prepare for the next attempt rather than
          // dropping an empty file into the session.
          prepare()
          event.preventDefault()
        }
      }}
      onClick={(event) => {
        if (playing) onSeek(fractionAt(event))
        else onToggle()
      }}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault()
          onToggle()
        }
      }}
    >
      <svg viewBox={`0 0 100 ${HEIGHT}`} preserveAspectRatio="none" aria-hidden="true">
        <path className="waveform__shape" d={shape} vectorEffect="non-scaling-stroke" />
        {playing ? (
          <>
            <rect className="waveform__played" x="0" y="0" width={progress * 100} height={HEIGHT} />
            <path
              className="waveform__head"
              d={`M${(progress * 100).toFixed(3)} 0V${HEIGHT}`}
              vectorEffect="non-scaling-stroke"
            />
          </>
        ) : null}
      </svg>
      {!peaks ? <span className="waveform__placeholder" aria-hidden="true" /> : null}
    </div>
  )
}
