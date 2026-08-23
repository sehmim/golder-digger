import { baseName } from '../../application/api'
import type { AnalyzeResult, Candidate } from '../../application/api'
import Waveform from '../../shared/components/Waveform'
import type { Preview } from '../gold-digger/usePreview'

export type GoldenResultsState =
  | { status: 'idle' }
  | { status: 'loading'; distance: number }
  | { status: 'ready'; distance: number; result: AnalyzeResult }
  | { status: 'error'; distance: number; message: string }

interface GoldenResultsProps {
  state: Exclude<GoldenResultsState, { status: 'idle' }>
  preview: Preview
  /** Playback is stretched to this, so the waveforms are drawn to it too. */
  sessionBpm: number | null
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

export default function GoldenResults({
  state,
  preview,
  sessionBpm,
  onBack
}: GoldenResultsProps): React.JSX.Element {
  const files = state.status === 'ready' ? uniqueFiles(state.result.results) : []

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
          <>
            {/* <div className="golden-results__mode">
              <button
                type="button"
                data-active={preview.candidateOnly || undefined}
                onClick={() => preview.setCandidateOnly(true)}
              >
                Just the sample
              </button>
              <button
                type="button"
                data-active={!preview.candidateOnly || undefined}
                onClick={() => preview.setCandidateOnly(false)}
              >
                Over your session
              </button>
              {sessionBpm ? <small>stretched to {Math.round(sessionBpm)} BPM</small> : null}
            </div> */}
            <ol className="golden-results__list">
              {files.map((candidate) => {
                const isPlaying = preview.playing === candidate.chunk_id
                return (
                  <li
                    key={candidate.chunk_id}
                    title={candidate.path}
                    data-playing={isPlaying || undefined}
                  >
                    <span className="golden-results__file">
                      <strong>{baseName(candidate.path)}</strong>
                      {resultMeta(candidate) ? <small>{resultMeta(candidate)}</small> : null}
                    </span>
                    <Waveform
                      chunkId={candidate.chunk_id}
                      path={candidate.path}
                      bpm={candidate.bpm}
                      sessionBpm={sessionBpm}
                      playing={isPlaying}
                      loading={preview.loading === candidate.chunk_id}
                      progress={isPlaying ? preview.progress : 0}
                      onToggle={() => preview.toggle(candidate.chunk_id)}
                      onSeek={preview.seek}
                    />
                  </li>
                )
              })}
            </ol>
            {preview.error ? (
              <p className="golden-results__message" data-error>{preview.error}</p>
            ) : null}
          </>
        ) : null}
      </div>
    </section>
  )
}
