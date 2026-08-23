/**
 * The DISTANCE dial, as a hardware knob with eleven detents.
 *
 * Detents rather than a continuous sweep because the value is a target novelty
 * percentile, not a gain: a musician wants to say "one notch further out" and be
 * able to get back to where they were.
 */
import { useRef } from 'react'

export const MIN = 1
export const MAX = 11

/** Total sweep of the pointer, split evenly across the detents. */
const SWEEP = 280
/** Pixels of drag per detent. Shallow enough that the whole range is one gesture. */
const PIXELS_PER_STEP = 22

const TICKS = Array.from({ length: MAX - MIN + 1 }, (_, index) => index + MIN)

export function angleOf(value: number): number {
  return -SWEEP / 2 + ((value - MIN) / (MAX - MIN)) * SWEEP
}

interface KnobProps {
  value: number
  onChange: (value: number) => void
  disabled?: boolean
  label: string
}

function clamp(value: number): number {
  return Math.min(MAX, Math.max(MIN, Math.round(value)))
}

export default function Knob({ value, onChange, disabled, label }: KnobProps): React.JSX.Element {
  const drag = useRef<{ y: number; from: number } | null>(null)

  function onPointerDown(event: React.PointerEvent<HTMLDivElement>): void {
    if (disabled) return
    drag.current = { y: event.clientY, from: value }
    event.currentTarget.setPointerCapture(event.pointerId)
  }

  function onPointerMove(event: React.PointerEvent<HTMLDivElement>): void {
    if (!drag.current) return
    // Up is more distant, which is the direction the numbers climb.
    const steps = (drag.current.y - event.clientY) / PIXELS_PER_STEP
    const next = clamp(drag.current.from + steps)
    if (next !== value) onChange(next)
  }

  function onPointerUp(event: React.PointerEvent<HTMLDivElement>): void {
    drag.current = null
    event.currentTarget.releasePointerCapture(event.pointerId)
  }

  function onKeyDown(event: React.KeyboardEvent<HTMLDivElement>): void {
    if (disabled) return
    const step = { ArrowUp: 1, ArrowRight: 1, ArrowDown: -1, ArrowLeft: -1 }[event.key]
    if (step) {
      onChange(clamp(value + step))
    } else if (event.key === 'Home') {
      onChange(MIN)
    } else if (event.key === 'End') {
      onChange(MAX)
    } else {
      return
    }
    event.preventDefault()
  }

  return (
    <div className="knob-well">
      <div className="knob-ticks" aria-hidden="true">
        {TICKS.map((tick) => (
          <span
            key={tick}
            className="knob-tick"
            data-on={tick <= value}
            style={{ transform: `rotate(${angleOf(tick)}deg) translateY(-74px)` }}
          />
        ))}
      </div>

      <div
        className="knob"
        role="slider"
        tabIndex={disabled ? -1 : 0}
        aria-label={label}
        aria-valuemin={MIN}
        aria-valuemax={MAX}
        aria-valuenow={value}
        aria-disabled={disabled || undefined}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onKeyDown={onKeyDown}
        onWheel={(event) => {
          if (!disabled) onChange(clamp(value + (event.deltaY < 0 ? 1 : -1)))
        }}
      >
        <div className="knob-face" style={{ transform: `rotate(${angleOf(value)}deg)` }}>
          <span className="knob-pointer" />
        </div>
        <span className="knob-value">{value}</span>
      </div>
    </div>
  )
}
