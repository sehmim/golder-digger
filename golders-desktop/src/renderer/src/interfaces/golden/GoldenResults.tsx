import { useState } from 'react'
import { baseName } from '../../application/api'
import type { AnalyzeResult, Candidate } from '../../application/api'
import { waveformHeights } from './waveform'

export type GoldenResultsState =
  | { status: 'idle' }
  | { status: 'loading'; distance: number }
  | { status: 'ready'; distance: number; result: AnalyzeResult }
  | { status: 'error'; distance: number; message: string }

interface GoldenResultsProps {
  state: Exclude<GoldenResultsState, { status: 'idle' }>
  onBack: () => void
}

function uniqueFiles(candidates: Candidate[]): Candidate[] {
  const seen = new Set<string>()
  return candidates.filter((candidate) => {
    if (seen.has(candidate.path)) return false
    seen.add(candidate.path)
    return true
  })
}

function resultMeta(candidate: Candidate): string {
  return [
    candidate.role,
    candidate.bpm ? `${Math.round(candidate.bpm)} BPM` : null,
    candidate.tonic
  ]
    .filter(Boolean)
    .join(' · ')
}

export default function GoldenResults({ state, onBack }: GoldenResultsProps): React.JSX.Element {
  const files = state.status === 'ready' ? uniqueFiles(state.result.results) : []
  const [playing, setPlaying] = useState<string | null>(null)
  const [looping, setLooping] = useState<string | null>(null)

  return (
    <section className="golden-results" aria-label="Ranked sounds">
      <button
        type="button"
        className="golden-results__close"
        onClick={onBack}
        aria-label="Close results"
        title="Close results"
      >
        ×
      </button>

      <div className="golden-results__body" aria-live="polite">
        {state.status === 'loading' ? (
          <span className="spinner spinner--large" aria-label="Ranking sounds" />
        ) : null}

        {state.status === 'error' ? (
          <div className="golden-results__error">
            <span className="golden-results__error-mark" aria-hidden="true">
              !
            </span>
            <p className="golden-results__message" data-error>
              search failed
              <br />
              <span>{state.message}</span>
            </p>
          </div>
        ) : null}

        {state.status === 'ready' && files.length === 0 ? (
          <p className="golden-results__message">
            No matching sounds
            <br />
            <span>nothing this far out still fits the set — try turning back</span>
          </p>
        ) : null}

        {state.status === 'ready' && files.length > 0 ? (
          <ol className="golden-results__list">
            {files.map((candidate) => {
              const isPlaying = playing === candidate.chunk_id
              const isLooping = looping === candidate.chunk_id
              return (
                <li key={candidate.chunk_id} title={candidate.path} data-playing={isPlaying || undefined}>
                  <span className="golden-results__bar" />
                  <span className="golden-results__file">
                    <strong>{baseName(candidate.path)}</strong>
                    {resultMeta(candidate) ? <small>{resultMeta(candidate)}</small> : null}
                  </span>
                  <span className="golden-results__wave" aria-hidden="true">
                    {waveformHeights(candidate.chunk_id).map((height, index) => (
                      <span key={index} style={{ height: `${height}px` }} />
                    ))}
                  </span>
                  <span className="golden-results__transport">
                    <button
                      type="button"
                      aria-label="Play"
                      onClick={() => setPlaying(isPlaying ? null : candidate.chunk_id)}
                    >
                      ▶
                    </button>
                    <button type="button" aria-label="Stop" onClick={() => setPlaying(null)}>
                      ■
                    </button>
                    <button
                      type="button"
                      aria-label="Loop"
                      data-active={isLooping || undefined}
                      onClick={() => setLooping(isLooping ? null : candidate.chunk_id)}
                    >
                      ↻
                    </button>
                  </span>
                </li>
              )
            })}
          </ol>
        ) : null}
      </div>
    </section>
  )
}
