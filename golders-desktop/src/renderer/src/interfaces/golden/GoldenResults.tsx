import { useEffect, useState } from 'react'
import { baseName } from '../../application/api'
import type { AnalyzeResult, Candidate, Network } from '../../application/api'
import Waveform from '../../shared/components/Waveform'
import type { Preview } from '../gold-digger/usePreview'
import TransitMap from './TransitMap'

export type GoldenResultsState =
  | { status: 'idle' }
  | { status: 'loading'; distance: number }
  | { status: 'ready'; distance: number; result: AnalyzeResult }
  | { status: 'error'; distance: number; message: string }

export type GoldenNetworkState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'ready'; network: Network }
  | { status: 'error'; message: string }

interface GoldenResultsProps {
  state: Exclude<GoldenResultsState, { status: 'idle' }>
  network: GoldenNetworkState
  preview: Preview
  /** Playback is stretched to this, so the waveforms are drawn to it too. */
  sessionBpm: number | null
  onBack: () => void
  /** Fetched lazily: the map asks the engine a different question than the dial. */
  onShowMap: () => void
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
  ].filter(Boolean).join(' · ')
}

export default function GoldenResults({
  state,
  network,
  preview,
  sessionBpm,
  onBack,
  onShowMap
}: GoldenResultsProps): React.JSX.Element {
  const [view, setView] = useState<'list' | 'map'>('list')
  const files = state.status === 'ready' ? uniqueFiles(state.result.results) : []

  // Escape closes. The × can be reached by mouse, but a modal that only exits
  // through one 44px target has no way out the moment anything covers it.
  useEffect(() => {
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') onBack()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onBack])

  return (
    <section
      className="golden-results"
      aria-label="Ranked sounds"
      onClick={(event) => {
        // Only the backdrop itself -- a click that started on a waveform or a
        // mode button bubbles here and must not be read as "dismiss".
        if (event.target === event.currentTarget) onBack()
      }}
    >
      <button
        type="button"
        className="golden-results__close"
        onClick={onBack}
        aria-label="Close results"
        title="Close results"
      >
        ×
      </button>

      {/* Two answers to one context. The dial asks "how far", the map asks
          "far in what respect" -- they are different questions, so the map is
          a view rather than another sort order. */}
      {state.status === 'ready' ? (
        <div className="golden-results__views" role="tablist" aria-label="Result view">
          <button
            type="button"
            role="tab"
            aria-selected={view === 'list'}
            data-active={view === 'list' || undefined}
            onClick={() => setView('list')}
          >
            Ranked
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={view === 'map'}
            data-active={view === 'map' || undefined}
            onClick={() => {
              setView('map')
              if (network.status === 'idle') onShowMap()
            }}
          >
            Map
          </button>
        </div>
      ) : null}

      <div className="golden-results__body" aria-live="polite">
        {state.status === 'ready' && view === 'map' ? (
          <MapView network={network} preview={preview} />
        ) : null}

        {state.status === 'loading' ? (
          <span className="spinner spinner--large" aria-label="Ranking sounds" />
        ) : null}

        {state.status === 'error' ? (
          <p className="golden-results__message" data-error>{state.message}</p>
        ) : null}

        {state.status === 'ready' && view === 'list' && files.length === 0 ? (
          <p className="golden-results__message">No matching sounds.</p>
        ) : null}

        {state.status === 'ready' && view === 'list' && files.length > 0 ? (
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

function MapView({
  network,
  preview
}: {
  network: GoldenNetworkState
  preview: Preview
}): React.JSX.Element {
  if (network.status === 'loading' || network.status === 'idle') {
    return <span className="spinner spinner--large" aria-label="Drawing the lines" />
  }
  if (network.status === 'error') {
    return <p className="golden-results__message" data-error>{network.message}</p>
  }
  return (
    <TransitMap
      network={network.network}
      onPreview={preview.toggle}
      playing={preview.playing}
    />
  )
}
