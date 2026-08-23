import { useRef, useState } from 'react'
import type { KnobStyle } from '../../application/ApplicationState'

const DISTANCE_STEPS = [10, 30, 50, 70, 90] as const
const STEP_LABELS = ['Closest', 'Familiar', 'Balanced', 'Unexpected', 'Far out'] as const
const SWEEP = 280
const PIXELS_PER_STEP = 24

interface GoldenKnobProps {
  value: number
  onChange: (value: number) => void
  onCommit: (value: number) => void
  style: KnobStyle
  disabled?: boolean
}

function stepIndex(value: number): number {
  let nearest = 0
  for (let index = 1; index < DISTANCE_STEPS.length; index += 1) {
    if (Math.abs(DISTANCE_STEPS[index] - value) < Math.abs(DISTANCE_STEPS[nearest] - value)) {
      nearest = index
    }
  }
  return nearest
}

function stepAt(index: number): number {
  const clamped = Math.min(DISTANCE_STEPS.length - 1, Math.max(0, index))
  return DISTANCE_STEPS[clamped]
}

export default function GoldenKnob({
  value,
  onChange,
  onCommit,
  style,
  disabled = false
}: GoldenKnobProps): React.JSX.Element {
  const drag = useRef<{
    startY: number
    startValue: number
    currentValue: number
    changed: boolean
  } | null>(null)
  const [dragging, setDragging] = useState(false)
  const position = stepIndex(value)
  const angle = -SWEEP / 2 + (position / (DISTANCE_STEPS.length - 1)) * SWEEP

  return (
    <button
      className="golden-knob"
      data-style={style}
      data-dragging={dragging || undefined}
      type="button"
      role="slider"
      aria-label={disabled ? 'Knob unavailable until context audio is resolved' : 'Knob'}
      aria-valuemin={1}
      aria-valuemax={DISTANCE_STEPS.length}
      aria-valuenow={position + 1}
      aria-valuetext={STEP_LABELS[position]}
      disabled={disabled}
      onPointerDown={(event) => {
        if (disabled) return
        event.currentTarget.setPointerCapture(event.pointerId)
        drag.current = { startY: event.clientY, startValue: value, currentValue: value, changed: false }
        setDragging(true)
      }}
      onPointerMove={(event) => {
        if (disabled || !drag.current) return
        const startPosition = stepIndex(drag.current.startValue)
        const offset = Math.round((drag.current.startY - event.clientY) / PIXELS_PER_STEP)
        const next = stepAt(startPosition + offset)
        drag.current.currentValue = next
        drag.current.changed ||= next !== drag.current.startValue
        onChange(next)
      }}
      onPointerUp={(event) => {
        if (disabled) return
        event.currentTarget.releasePointerCapture(event.pointerId)
        const completed = drag.current
        drag.current = null
        setDragging(false)
        if (completed?.changed) onCommit(completed.currentValue)
      }}
      onPointerCancel={() => {
        drag.current = null
        setDragging(false)
      }}
      onKeyDown={(event) => {
        if (disabled) return
        if (event.key === 'ArrowUp' || event.key === 'ArrowRight') {
          event.preventDefault()
          onChange(stepAt(position + 1))
        }
        if (event.key === 'ArrowDown' || event.key === 'ArrowLeft') {
          event.preventDefault()
          onChange(stepAt(position - 1))
        }
      }}
      onKeyUp={(event) => {
        if (disabled) return
        if (
          event.key === 'ArrowUp' ||
          event.key === 'ArrowRight' ||
          event.key === 'ArrowDown' ||
          event.key === 'ArrowLeft'
        ) {
          onCommit(value)
        }
      }}
    >
      <span className="golden-knob__notches" aria-hidden="true">
        {DISTANCE_STEPS.map((step, index) => {
          const notchAngle = -SWEEP / 2 + (index / (DISTANCE_STEPS.length - 1)) * SWEEP
          return (
            <span
              key={step}
              className="golden-knob__notch"
              data-active={index === position || undefined}
              style={{ transform: `rotate(${notchAngle}deg)` }}
            />
          )
        })}
      </span>
      <span className="golden-knob__face" aria-hidden="true">
        <span className="golden-knob__indicator" style={{ transform: `rotate(${angle}deg)` }} />
      </span>
    </button>
  )
}
