/**
 * The results view: one dial, one list.
 *
 * The dial is the whole interface on purpose -- Fit already decided what is
 * allowed through, so the only thing left to steer is how far out to look.
 */
import { useEffect, useRef, useState } from 'react'
import { baseName } from '../../../application/api'
import type { AnalyzeResult, Candidate, SessionSet } from '../../../application/api'
import Waveform from '../../../shared/components/Waveform'
import { usePreview } from '../usePreview'
import Knob, { MAX, MIN } from '../components/Knob'

interface DigStepProps {
  set: SessionSet
  activeRoots: string[] | null
  onBack: () => void
}

const DEFAULT_NOTCH = 6
const RESULT_COUNT = 12
/** Re-ranking is cheap, but not so cheap that every detent of a sweep deserves a call. */
const SETTLE_MS = 220

/** What each notch means, in the words a producer would use. */
const CAPTIONS = [
  'the obvious neighbours',
  'safe swaps',
  'close cousins',
  'familiar, not identical',
  'a step sideways',
  'the middle ground',
  'an unexpected fit',
  'off the beaten path',
  'strange, still compatible',
  'far out',
  'the deep end'
]

/** Notch 1-11 to the API's 0-100 novelty percentile. */
function distanceOf(notch: number): number {
  return ((notch - MIN) / (MAX - MIN)) * 100
}

/** Where Fit's tempo and key came from -- Live's own numbers, or the samples.
 *
 * Worth a line of its own: the two answers differ whenever a set's resolved
 * samples are one-shots, and a producer reading a bad match deserves to know
 * which tempo it was matched against.
 */
function anchorLine(result: AnalyzeResult): string {
  const anchored = new Set(result.session_context)
  const bpm = result.context.bpm ? `${Math.round(result.context.bpm)} BPM` : 'no tempo'
  const key = result.context.tonic ?? 'no key'
  const from = (field: 'bpm' | 'tonic'): string => (anchored.has(field) ? 'from Live' : 'from samples')
  return `matching against ${bpm} (${from('bpm')}) · ${key} (${from('tonic')})`
}

/** Why the dial is not a measurement yet, in terms of this corpus.
 *
 * Phrased off the counts rather than off a mode flag: the engine can be running
 * real extraction while the rows it ranks were written under mock, which is the
 * normal state of a library part-way through being re-ingested. Novelty is a
 * percentile across the whole corpus, so synthesized vectors move the numbers
 * for the measured chunks too.
 */
function syntheticWarning(result: AnalyzeResult): string {
  const { synthetic_chunks: bad, corpus_size: all } = result
  const scope =
    bad >= all
      ? 'Every chunk in your library was'
      : `${bad} of your ${all} chunks were`
  return (
    `${scope} ingested before real extraction, so their “sounds like” vector is ` +
    'synthesized from the file hash. Keys and tempos are real; the distances are not ' +
    'measurements. Add those folders again to replace them — they will be re-analysed, ' +
    'not skipped.'
  )
}

function meta(candidate: Candidate): string {
  const parts = [`fit ${candidate.fit.toFixed(2)}`, `novelty ${Math.round(candidate.novelty * 100)}`]
  if (candidate.bpm) parts.push(`${candidate.bpm} BPM`)
  if (candidate.tonic) parts.push(`${candidate.tonic} ${candidate.is_major ? 'maj' : 'min'}`)
  return parts.join(' · ')
}

export default function DigStep({ set, activeRoots, onBack }: DigStepProps): React.JSX.Element {
  const [notch, setNotch] = useState(DEFAULT_NOTCH)
  const [result, setResult] = useState<AnalyzeResult | null>(null)
  const [working, setWorking] = useState(true)
  const [error, setError] = useState<string | null>(null)
  // Candidates sound at the session's tempo, mixed under it, so what is judged
  // is the combination rather than a clip at a foreign tempo.
  const preview = usePreview({ bpm: set.session.tempo, contextIds: set.context_ids })

  // Only the newest request may write state: a sweep fires several in order.
  const generation = useRef(0)
  const activeRootsKey = activeRoots?.join('\u0000') ?? null

  useEffect(() => {
    const mine = ++generation.current
    setWorking(true)

    const timer = setTimeout(() => {
      void window.desktop
        // The set's own path, so the engine anchors tempo and key on what Live
        // declares rather than on whichever samples happened to resolve.
        .analyze(set.context_ids, distanceOf(notch), RESULT_COUNT, set.session.path, activeRoots)
        .then((next) => {
          if (generation.current !== mine) return
          setResult(next)
          setError(null)
        })
        .catch((cause) => {
          if (generation.current !== mine) return
          setError(String(cause instanceof Error ? cause.message : cause))
        })
        .finally(() => {
          if (generation.current === mine) setWorking(false)
        })
    }, SETTLE_MS)

    return () => clearTimeout(timer)
  }, [activeRootsKey, notch, set.context_ids, set.session.path])

  const results = result?.results ?? []

  return (
    <section className="dig">
      <div className="pedal">
        <header className="pedal-head">
          <p className="set-name">{set.session.name}</p>
          <p className="set-meta">
            {set.session.tempo ? ` · ${set.session.tempo} BPM` : ''}
            {set.session.key ? ` · ${set.session.key}` : ''}
          </p>
        </header>

        <Knob label="Distance" value={notch} onChange={setNotch} />

        <p className="knob-label">Distance</p>
        <p className="knob-caption">{CAPTIONS[notch - MIN]}</p>

        <div className="results" data-working={working || undefined}>

          <div className="audition-mode">
            <button
              type="button"
              data-active={!preview.candidateOnly || undefined}
              onClick={() => preview.setCandidateOnly(false)}
            >
              {set.session.tempo ? `over the session · ${set.session.tempo} BPM` : 'over the session'}
            </button>
            <button
              type="button"
              data-active={preview.candidateOnly || undefined}
              onClick={() => preview.setCandidateOnly(true)}
            >
              on its own
            </button>
          </div>

          <ul className="result-list">
            {results.map((candidate) => {
              const isPlaying = preview.playing === candidate.chunk_id
              const isLoading = preview.loading === candidate.chunk_id

              return (
                <li key={candidate.chunk_id} data-playing={isPlaying || undefined}>
                  <button
                    className="play-button"
                    type="button"
                    aria-label={`${isPlaying ? 'Stop' : 'Play'} ${baseName(candidate.path)}`}
                    onClick={() => preview.toggle(candidate.chunk_id)}
                  >
                    {isLoading ? (
                      <span className="spinner" aria-hidden="true" />
                    ) : (
                      <svg viewBox="0 0 24 24" aria-hidden="true">
                        {isPlaying ? (
                          <path d="M9 6.5v11M15 6.5v11" />
                        ) : (
                          <path d="M8.5 6.2l9 5.8-9 5.8V6.2Z" />
                        )}
                      </svg>
                    )}
                  </button>

                  <span className="entry" title={candidate.path}>
                    <span className="entry-name">{baseName(candidate.path)}</span>
                    <span className="entry-meta">{meta(candidate)}</span>
                    <Waveform
                      chunkId={candidate.chunk_id}
                      path={candidate.path}
                      bpm={candidate.bpm}
                      sessionBpm={set.session.tempo}
                      playing={isPlaying}
                      loading={isLoading}
                      progress={isPlaying ? preview.progress : 0}
                      onToggle={() => preview.toggle(candidate.chunk_id)}
                      onSeek={preview.seek}
                    />
                    {candidate.tags?.length ? (
                      <span className="tags">
                        {candidate.tags.map((tag) => (
                          <span className="tag" key={tag}>
                            {tag}
                          </span>
                        ))}
                      </span>
                    ) : null}
                  </span>

                  <span
                    className={`role-chip role-${candidate.role ?? 'none'}`}
                    title={candidate.role_source === 'clap' ? 'inferred from tags' : undefined}
                  >
                    {candidate.role ?? '—'}
                    {candidate.role_source === 'clap' ? '?' : ''}
                  </span>
                </li>
              )
            })}
          </ul>

          {!working && results.length === 0 ? (
            <p className="hint">Nothing cleared the fit gate. Ingest more of your library.</p>
          ) : null}

          {result?.synthetic_novelty ? (
            <p className="hint hint--warn">{syntheticWarning(result)}</p>
          ) : null}
        </div>
      </div>

      {error ? <p className="error">{error}</p> : null}
      {preview.error ? <p className="error">{preview.error}</p> : null}

      <button className="back-button" type="button" onClick={onBack}>
        ← Back to your project
      </button>
    </section>
  )
}
