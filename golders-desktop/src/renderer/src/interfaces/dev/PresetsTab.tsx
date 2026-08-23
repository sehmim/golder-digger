/**
 * What each of the five postures does, and what it actually returned.
 *
 * The table and the notes come from GET /presets rather than being written out
 * here, so the numbers on screen are provably the numbers the engine scored
 * with. The comparison below runs all five against the connected project: a
 * preset whose results are identical to Companion's is not doing any work on
 * this library, and no amount of reading its description would say so.
 */
import { useEffect, useState } from 'react'
import type { AnalyzeResult, Preset, PresetList, SessionSet } from '../../application/api'

const RUN_K = 12

interface Run {
  preset: Preset
  result: AnalyzeResult
}

interface PresetsTabProps {
  project: SessionSet | null
  activeRoots: string[] | null
}

function mean(values: number[]): number {
  return values.length ? values.reduce((a, b) => a + b, 0) / values.length : 0
}

/** How much of this preset's twelve the reference preset also returned. */
function overlap(run: Run, reference: Run | undefined): string {
  if (!reference || reference.preset.key === run.preset.key) return '—'
  const seen = new Set(reference.result.results.map((c) => c.chunk_id))
  const shared = run.result.results.filter((c) => seen.has(c.chunk_id)).length
  return `${shared}/${run.result.results.length}`
}

export default function PresetsTab({
  project,
  activeRoots
}: PresetsTabProps): React.JSX.Element {
  const [list, setList] = useState<PresetList | null>(null)
  const [runs, setRuns] = useState<Run[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    void window.desktop
      .presets()
      .then((next) => !cancelled && setList(next))
      .catch((cause) => !cancelled && setError(String(cause)))
    return () => {
      cancelled = true
    }
  }, [])

  // The runs describe one context. Keeping them on screen after the project
  // changed would attribute one set's results to another.
  useEffect(() => setRuns(null), [project?.session.path])

  const canRun = Boolean(project && project.context_ids.length > 0)

  async function runAll(): Promise<void> {
    if (!list || !project) return
    setBusy(true)
    setError(null)
    try {
      const out: Run[] = []
      for (const preset of list.presets) {
        // Sequential on purpose: the backend caches per request and these share
        // a corpus, so firing five at once only contends for the same lock.
        const result = await window.desktop.analyze(
          project.context_ids, null, RUN_K, project.session.path, activeRoots, preset.key
        )
        out.push({ preset, result })
      }
      setRuns(out)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause))
    } finally {
      setBusy(false)
    }
  }

  if (error && !list) return <p className="dev-files__message error">{error}</p>
  if (!list) return <p className="dev-files__message">Loading presets…</p>

  const reference = runs?.find((r) => r.preset.key === 'companion')

  return (
    <section className="dev-presets" aria-label="Scoring presets">
      <header className="dev-presets__toolbar">
        <span>
          Five postures, safest first. Each sets the novelty target <em>and</em> the gate.
        </span>
        <button
          type="button"
          onClick={() => void runAll()}
          disabled={!canRun || busy}
          title={canRun ? undefined : 'Connect an Ableton project with resolved audio first'}
        >
          {busy ? 'Running…' : 'Run all five on this project'}
        </button>
      </header>

      {error ? <p className="dev-files__message error">{error}</p> : null}

      <div className="dev-preset-table">
        <div className="dev-preset-table__head" aria-hidden="true">
          <span>Preset</span>
          <span>Distance</span>
          <span>Fit floor</span>
          <span>Band</span>
          <span>Redundancy</span>
          <span>Instrument</span>
          <span>Result</span>
        </div>
        <ol>
          {list.presets.map((preset, index) => {
            const run = runs?.find((r) => r.preset.key === preset.key)
            return (
              <li key={preset.key} data-rank={index + 1}>
                <div className="dev-preset-row">
                  <span className="dev-preset-name">
                    <strong>
                      {index + 1}. {preset.name}
                    </strong>
                    <small>{preset.blurb}</small>
                  </span>
                  <span>{preset.distance}</span>
                  <span>{preset.fit_floor.toFixed(2)}</span>
                  <span>{preset.bandwidth.toFixed(2)}</span>
                  <span>{preset.redundancy.toFixed(2)}</span>
                  <span>{preset.role_mode}</span>
                  <span className="dev-preset-result">
                    {run ? (
                      <>
                        <strong>nov {mean(run.result.results.map((c) => c.novelty)).toFixed(2)}</strong>
                        <small>
                          fit {mean(run.result.results.map((c) => c.fit)).toFixed(2)} · shared{' '}
                          {overlap(run, reference)}
                          {run.result.fit_floor_relaxed
                            ? ` · floor relaxed to ${run.result.fit_floor.toFixed(2)}`
                            : ''}
                        </small>
                      </>
                    ) : (
                      <small>not run</small>
                    )}
                  </span>
                </div>
                <p className="dev-preset-notes">{preset.notes}</p>
              </li>
            )
          })}
        </ol>
      </div>

      <section className="dev-preset-legend">
        <h3>What the columns mean</h3>
        <dl>
          <div>
            <dt>Distance</dt>
            <dd>
              Where in the corpus-wide ranking of CLAP distance to aim, 0–100. It is a
              target percentile, not a similarity threshold: 75 means “about three
              quarters of the library sounds closer to your set than this does”.
            </dd>
          </div>
          <div>
            <dt>Fit floor</dt>
            <dd>
              The compatibility bar. Fit is the geometric mean of key, tempo and
              instrument, so one bad component sinks a candidate whatever the other two say.
              When too few candidates clear the bar it drops in {list.fit_floor_min}-limited
              steps until the pool is deep enough — the Result column says when that
              happened, and a preset that always relaxes is not the preset you chose.
            </dd>
          </div>
          <div>
            <dt>Band</dt>
            <dd>
              How tightly the novelty target is held. Narrow returns twelve results at
              nearly the same distance; wide lets the selection spread either side of it.
            </dd>
          </div>
          <div>
            <dt>Redundancy</dt>
            <dd>
              Penalty for resembling something already picked. Selection is greedy, so
              this is what stops all twelve being the same sound from one folder.
            </dd>
          </div>
          <div>
            <dt>Instrument</dt>
            <dd>
              How hard the tool argues against handing you another of what you already
              have. A candidate doing the same job as something already in your set
              scores{' '}
              {Object.entries(list.role_modes)
                .map(([mode, w]) => `${mode} ${w.same}`)
                .join(', ')}
              . At <code>off</code> the term leaves the geometric mean entirely rather
              than being weighted down and still quietly voting.
            </dd>
          </div>
        </dl>
      </section>
    </section>
  )
}
