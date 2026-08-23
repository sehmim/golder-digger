import { useRef, useState } from 'react'
import type { KnobStyle } from '../../application/ApplicationState'

const MIN = 0
const MAX = 100
const SWEEP = 280

interface GoldenKnobProps {
  value: number
  onChange: (value: number) => void
  style: KnobStyle
}

function clamp(value: number): number {
  return Math.min(MAX, Math.max(MIN, value))
}

export default function GoldenKnob({ value, onChange, style }: GoldenKnobProps): React.JSX.Element {
  const drag = useRef<{ startY: number; startValue: number } | null>(null)
  const [dragging, setDragging] = useState(false)
  const angle = -SWEEP / 2 + (value / MAX) * SWEEP

  return (
    <button
      className="golden-knob"
      data-style={style}
      data-dragging={dragging || undefined}
      type="button"
      role="slider"
      aria-label="Knob"
      aria-valuemin={MIN}
      aria-valuemax={MAX}
      aria-valuenow={value}
      onPointerDown={(event) => {
        event.currentTarget.setPointerCapture(event.pointerId)
        drag.current = { startY: event.clientY, startValue: value }
        setDragging(true)
      }}
      onPointerMove={(event) => {
        if (!drag.current) return
        onChange(clamp(Math.round(drag.current.startValue + (drag.current.startY - event.clientY))))
      }}
      onPointerUp={(event) => {
        event.currentTarget.releasePointerCapture(event.pointerId)
        drag.current = null
        setDragging(false)
      }}
      onPointerCancel={() => {
        drag.current = null
        setDragging(false)
      }}
      onKeyDown={(event) => {
        if (event.key === 'ArrowUp' || event.key === 'ArrowRight') {
          event.preventDefault()
          onChange(clamp(value + 1))
        }
        if (event.key === 'ArrowDown' || event.key === 'ArrowLeft') {
          event.preventDefault()
          onChange(clamp(value - 1))
        }
      }}
    >
      <span className="golden-knob__face" aria-hidden="true">
        <span className="golden-knob__indicator" style={{ transform: `rotate(${angle}deg)` }} />
      </span>
    </button>
  )
}
