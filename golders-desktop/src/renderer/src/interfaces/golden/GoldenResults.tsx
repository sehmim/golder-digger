import { baseName } from '../../application/api'
import type { AnalyzeResult, Candidate } from '../../application/api'

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
  ].filter(Boolean).join(' · ')
}

export default function GoldenResults({ state, onBack }: GoldenResultsProps): React.JSX.Element {
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
          <p className="golden-results__message" data-error>{state.message}</p>
        ) : null}

        {state.status === 'ready' && files.length === 0 ? (
          <p className="golden-results__message">No matching sounds.</p>
        ) : null}

        {state.status === 'ready' && files.length > 0 ? (
          <ol className="golden-results__list">
            {files.map((candidate) => (
              <li key={candidate.chunk_id} title={candidate.path}>
                <span className="golden-results__file">
                  <strong>{baseName(candidate.path)}</strong>
                  {resultMeta(candidate) ? <small>{resultMeta(candidate)}</small> : null}
                </span>
              </li>
            ))}
          </ol>
        ) : null}
      </div>
    </section>
  )
}
