/**
 * Whether the library can support the scoring at all.
 *
 * A file count says a folder was read. It does not say the engine can tell
 * anything apart inside it, and those are different questions. Each block here
 * answers one term of Fit or Novelty directly: provenance is whether the
 * DISTANCE dial is a measurement, key confidence is whether harmony contributes
 * anything, tempo coverage is whether the corpus is loops or one-shots, and the
 * instrument split is how much a human named versus a classifier guessed.
 */
import { useEffect, useState } from 'react'
import type { CorpusStats } from '../../application/api'

function pct(part: number, whole: number): string {
  return whole > 0 ? `${Math.round((100 * part) / whole)}%` : '—'
}

/** A labelled proportion bar. `tone` colours the share that is bad news. */
function Bar({
  segments,
  total
}: {
  segments: { label: string; count: number; tone?: 'good' | 'warn' | 'bad' }[]
  total: number
}): React.JSX.Element {
  return (
    <div className="dev-bar">
      <div className="dev-bar__track">
        {segments.map((s) => (
          <span
            key={s.label}
            data-tone={s.tone}
            style={{ flexGrow: total > 0 ? s.count : 0 }}
            title={`${s.label}: ${s.count.toLocaleString()} (${pct(s.count, total)})`}
          />
        ))}
      </div>
      <ul className="dev-bar__key">
        {segments.map((s) => (
          <li key={s.label} data-tone={s.tone}>
            <span />
            {s.label} <strong>{s.count.toLocaleString()}</strong>
            <small>{pct(s.count, total)}</small>
          </li>
        ))}
      </ul>
    </div>
  )
}

function Histogram({
  bins
}: {
  bins: { label: string; count: number; tone?: 'good' | 'warn' | 'bad' }[]
}): React.JSX.Element {
  const peak = Math.max(1, ...bins.map((b) => b.count))
  return (
    <ol className="dev-histogram">
      {bins.map((b) => (
        <li key={b.label} data-tone={b.tone}>
          <span className="dev-histogram__label">{b.label}</span>
          <span className="dev-histogram__bar">
            <span style={{ width: `${(100 * b.count) / peak}%` }} />
          </span>
          <span className="dev-histogram__count">{b.count.toLocaleString()}</span>
        </li>
      ))}
    </ol>
  )
}

export default function CorpusTab(): React.JSX.Element {
  const [stats, setStats] = useState<CorpusStats | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [refresh, setRefresh] = useState(0)

  useEffect(() => {
    let cancelled = false
    void window.desktop
      .corpusStats()
      .then((next) => !cancelled && setStats(next))
      .catch((cause) => !cancelled && setError(String(cause)))
    return () => {
      cancelled = true
    }
  }, [refresh])

  if (error) return <p className="dev-files__message error">{error}</p>
  if (!stats) return <p className="dev-files__message">Reading corpus…</p>

  const { provenance, key, tempo, roles, essentia } = stats
  const trusted = provenance.measured
  const named = roles.breakdown
    .filter((r) => r.role && r.source === 'filename')
    .reduce((a, r) => a + r.count, 0)
  const guessed = roles.breakdown
    .filter((r) => r.role && r.source === 'clap')
    .reduce((a, r) => a + r.count, 0)
  const manual = roles.breakdown
    .filter((r) => r.role && r.source === 'manual')
    .reduce((a, r) => a + r.count, 0)

  return (
    <section className="dev-corpus" aria-label="Corpus health">
      <header className="dev-corpus__toolbar">
        <span>
          {stats.chunks.toLocaleString()} chunks across {stats.files.toLocaleString()} files
        </span>
        <button type="button" onClick={() => setRefresh((v) => v + 1)}>
          Refresh
        </button>
      </header>

      <article className="dev-corpus__block">
        <h3>Is the DISTANCE dial a measurement?</h3>
        <p>
          Novelty is a distance in CLAP space. A chunk whose vector was synthesized
          from its file hash, or written before the column existed, carries no
          information about how anything sounds — so the dial is fiction in
          proportion to this bar.
        </p>
        <Bar
          total={stats.chunks}
          segments={[
            { label: 'measured', count: provenance.measured, tone: 'good' },
            { label: 'synthetic (mock)', count: provenance.synthetic, tone: 'bad' },
            { label: 'unknown (pre-column)', count: provenance.unknown, tone: 'warn' }
          ]}
        />
        {trusted < stats.chunks ? (
          <p className="dev-corpus__verdict" data-tone="warn">
            {(stats.chunks - trusted).toLocaleString()} chunks are not trustworthy for
            novelty. Re-ingest their folders with mock off to replace them.
          </p>
        ) : (
          <p className="dev-corpus__verdict" data-tone="good">
            Every vector is measured. Novelty means what it says.
          </p>
        )}
      </article>

      <article className="dev-corpus__block">
        <h3>Is harmony contributing anything?</h3>
        <p>
          Fit&apos;s harmony term is <code>c·raw + (1−c)·0.6</code>, where c is the
          weaker of the two key confidences. Below roughly 0.05 that collapses to a
          flat neutral — the term stops discriminating and every candidate scores the
          same on key. Drums and noise legitimately land there; the question is how
          much of the library does.
        </p>
        <Histogram
          bins={key.histogram.map((h) => ({
            label: `${h.from.toFixed(2)}–${h.to >= 1 ? '1.00' : h.to.toFixed(2)}`,
            count: h.count,
            tone: h.to <= 0.05 ? 'bad' : h.from >= 0.3 ? 'good' : 'warn'
          }))}
        />
        <p className="dev-corpus__verdict" data-tone={key.absent > stats.chunks / 2 ? 'warn' : 'good'}>
          {key.absent.toLocaleString()} chunks ({pct(key.absent, stats.chunks)}) have
          effectively no key evidence; {key.strong.toLocaleString()} are confident.
          Mean {key.mean_confidence.toFixed(3)}.
        </p>
      </article>

      <article className="dev-corpus__block">
        <h3>Loops or one-shots?</h3>
        <p>
          The rhythm term is ratio-aware, so 87 against 174 BPM is a match. A chunk
          with no tempo scores neutral instead — not rejected, but not sorted either.
        </p>
        <Histogram
          bins={tempo.histogram.map((h) => ({
            label: h.label,
            count: h.count,
            tone: h.label === 'none' ? 'warn' : undefined
          }))}
        />
      </article>

      <article className="dev-corpus__block">
        <h3>Who named the instruments?</h3>
        <p>
          The instrument decides whether a candidate complements the arrangement or
          duplicates it — it is a third of Fit, alongside key and tempo. A filename is
          a person&apos;s own label and outranks the classifier;
          &ldquo;unassigned&rdquo; means the term has nothing to say and scores
          neutral for that chunk whatever the preset.
        </p>
        <Bar
          total={stats.chunks}
          segments={[
            { label: 'from filename', count: named, tone: 'good' },
            { label: 'manual', count: manual, tone: 'good' },
            { label: 'guessed from CLAP tags', count: guessed, tone: 'warn' },
            { label: 'unassigned', count: roles.unassigned, tone: 'bad' }
          ]}
        />
        <ul className="dev-corpus__roles">
          {roles.breakdown
            .filter((r) => r.role)
            .map((r) => (
              <li key={`${r.role}:${r.source}`}>
                <strong>{r.role}</strong>
                <small>{r.source}</small>
                <span>{r.count.toLocaleString()}</span>
              </li>
            ))}
        </ul>
      </article>

      <article className="dev-corpus__block">
        <h3>Second opinion</h3>
        <p>
          Essentia characterises whole files independently of beat-this and librosa.
          Where the two name different keys, one of them is wrong about that file.
        </p>
        <dl className="dev-corpus__values">
          <div>
            <dt>Runner</dt>
            <dd>{essentia.mode ?? 'unavailable'}</dd>
          </div>
          <div>
            <dt>Covered</dt>
            <dd>
              {essentia.covered.toLocaleString()} / {essentia.files.toLocaleString()} files
            </dd>
          </div>
          <div>
            <dt>Agree on key</dt>
            <dd>{essentia.agree.toLocaleString()}</dd>
          </div>
          <div>
            <dt>Disagree</dt>
            <dd>{essentia.disagree.toLocaleString()}</dd>
          </div>
          <div>
            <dt>Neither named a key</dt>
            <dd>{essentia.no_key.toLocaleString()}</dd>
          </div>
        </dl>
      </article>
    </section>
  )
}
