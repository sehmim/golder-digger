import { useMemo, useState } from 'react'
import type { Line, Network, Stop } from '../../application/api'
import { baseName } from '../../application/api'

interface TransitMapProps {
  network: Network
  onPreview?: (chunkId: string) => void
  playing?: string | null
}

/** Where a stop sits across the track, as a percentage. The inset keeps the
 *  nearest stop clear of the interchange it just left and the farthest clear of
 *  the edge; `position` itself is a percentile and owns none of this. */
const RUN_START = 8
const RUN_LENGTH = 84

function across(position: number): number {
  return RUN_START + position * RUN_LENGTH
}

/**
 * The session as an interchange, and four lines leading out of it.
 *
 * A single DISTANCE dial can say how far but never in what respect. Drawn as
 * routes, "farther" becomes legible: ride green and the notes move, ride orange
 * and the pulse moves. Every stop already cleared the compatibility gate, so
 * the far end of a line is strange *and* still works — the product's whole
 * claim in one picture.
 *
 * Deliberately schematic, the way a metro map is: the horizontal axis is
 * position along the line, not any real distance, and the lines are parallel
 * because they are alternatives rather than a space you could travel
 * diagonally through.
 */
export default function TransitMap({
  network,
  onPreview,
  playing
}: TransitMapProps): React.JSX.Element {
  const [selected, setSelected] = useState<Stop | null>(null)

  const interchanges = useMemo(
    () => new Set(network.interchanges.map((i) => i.chunk_id)),
    [network.interchanges]
  )

  // Every line is drawn, including the ones this library cannot answer. A line
  // that silently vanishes takes its own absence with it: three rails on screen
  // look complete, and nothing tells you a fourth question exists and went
  // unasked. Greyed out, "we cannot measure this yet" is information.
  if (!network.lines.some((line) => line.available)) {
    return (
      <p className="transit-map__empty">
        No line has anything to show yet — ingest more of your library, or open the
        gate with a looser preset.
      </p>
    )
  }

  return (
    <div className="transit-map">
      <header className="transit-map__head">
        <span className="transit-map__origin-label">your session</span>
        <span className="transit-map__axis">
          nearer<i aria-hidden="true" />farther
        </span>
      </header>

      <ol className="transit-map__lines">
        {network.lines.map((line) => (
          <LineRow
            key={line.key}
            line={line}
            interchanges={interchanges}
            selected={selected}
            playing={playing ?? null}
            onSelect={setSelected}
            onPreview={onPreview}
          />
        ))}
      </ol>

      {selected ? (
        <aside className="transit-map__detail">
          <strong>{baseName(selected.path)}</strong>
          <span>{selected.why}</span>
          <small>
            {[
              selected.role,
              selected.bpm ? `${Math.round(selected.bpm)} BPM` : null,
              selected.tonic,
              `fit ${selected.fit.toFixed(2)}`
            ]
              .filter(Boolean)
              .join(' · ')}
          </small>
        </aside>
      ) : (
        <p className="transit-map__hint">
          Every stop already fits. Ride outward to reach the ones you would not
          have looked for.
        </p>
      )}
    </div>
  )
}

interface LineRowProps {
  line: Line
  interchanges: Set<string>
  selected: Stop | null
  playing: string | null
  onSelect: (stop: Stop) => void
  onPreview?: (chunkId: string) => void
}

function LineRow({
  line,
  interchanges,
  selected,
  playing,
  onSelect,
  onPreview
}: LineRowProps): React.JSX.Element {
  // Metro lines are named for where they end up, and so is this one: the last
  // stop is the strangest thing on it that still fits.
  const terminus = line.stops.length ? line.stops[line.stops.length - 1] : null

  return (
    <li
      className="transit-line"
      data-colour={line.colour}
      data-available={line.available || undefined}
    >
      <span className="transit-line__name">{line.key}</span>

      <div className="transit-line__track">
        {/* The rail stops at the terminus, the way a line does. A line whose pool
            ran thin therefore draws visibly shorter, which is true of it. */}
        <span
          className="transit-line__rail"
          aria-hidden="true"
          style={terminus ? { right: `${100 - across(terminus.position)}%` } : undefined}
        />
        <span className="transit-stop transit-stop--origin" aria-hidden="true" />
        {line.stops.map((stop) => {
          const isPlaying = playing === stop.chunk_id
          return (
            <button
              key={stop.chunk_id}
              type="button"
              className="transit-stop"
              style={{ left: `${across(stop.position)}%` }}
              data-interchange={interchanges.has(stop.chunk_id) || undefined}
              data-active={selected?.chunk_id === stop.chunk_id || undefined}
              data-playing={isPlaying || undefined}
              title={`${baseName(stop.path)} — ${stop.why}`}
              aria-label={`${baseName(stop.path)}, ${stop.why}`}
              onClick={() => {
                onSelect(stop)
                onPreview?.(stop.chunk_id)
              }}
            />
          )
        })}
      </div>

      <p className="transit-line__meta">
        <span className="transit-line__blurb">
          {line.available ? line.blurb : 'nothing in your library measures this yet'}
        </span>
        {line.fit_floor_relaxed ? (
          // A line that had to open its gate to fill up is a weaker claim than
          // one that did not, and from the drawing alone they are identical.
          <span
            className="transit-line__relaxed"
            title={
              `the compatibility gate opened to ${line.fit_floor.toFixed(2)} to` +
              ` find this many stops`
            }
          >
            gate opened
          </span>
        ) : null}
        {terminus ? (
          <span className="transit-line__terminus" title={baseName(terminus.path)}>
            {baseName(terminus.path)}
          </span>
        ) : null}
      </p>
    </li>
  )
}
