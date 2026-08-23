import { useRef, useState } from 'react'
import type { KnobStyle } from '../../application/ApplicationState'

const DISTANCE_STEPS = [10, 30, 50, 70, 90] as const
const STEP_LABELS = ['Obviously', 'Interesting', 'Groovy!', 'Craaaazy!', 'GOOOOOLD!'] as const
const SWEEP = 270
const PIXELS_PER_STEP = 24

// Tuned by eye, same spirit as the mockup's HEAT2 arrays: the dial visibly
// "heats up" toward the far end of the sweep, escalating glow/shadow per step.
const RING_LIGHT = '0 0 0 9px var(--color-surface), 0 0 0 10px #d9c08a'
const RING_DARK = '0 0 0 9px var(--color-surface), 0 0 0 10px #6f5a2c'

const FACE_LIGHT = [
  { g: '178deg, #c69732 0%, #b8862a 52%, #a2762a 100%', glow: 0 },
  { g: '172deg, #ddb257 0%, #c1912f 30%, #d8ab4c 62%, #a87e28 100%', glow: 0.22 },
  { g: '166deg, #f0d489 0%, #c99a35 26%, #e8c063 52%, #b3872b 78%, #d3a640 100%', glow: 0.3 },
  {
    g: '160deg, #fff0bd 0%, #d9ac47 20%, #b8862a 38%, #f5dfa2 56%, #c2932f 76%, #e3bc63 100%',
    glow: 0.4
  },
  {
    g: '154deg, #fffbe6 0%, #f0d68f 14%, #c2932f 30%, #fff6cf 46%, #d4a63d 60%, #ab7c22 76%, #ffeeb6 92%, #d9ac47 100%',
    glow: 0.55
  }
]

function faceStyle(index: number, style: KnobStyle): { background: string; boxShadow: string } {
  if (style === 'minimal') {
    return { background: 'transparent', boxShadow: 'none' }
  }
  const step = FACE_LIGHT[index]
  const ring = style === 'dark' ? RING_DARK : RING_LIGHT
  const glowShadow = step.glow
    ? `, 0 0 ${18 + index * 16}px rgba(214,166,62,${step.glow})`
    : ''
  return {
    background: `linear-gradient(${step.g})`,
    boxShadow: `0 ${14 + index * 2}px ${28 + index * 4}px rgba(120,84,18,${0.24 + index * 0.03}), inset 0 1px 0 rgba(255,250,225,${0.4 + index * 0.14}), ${ring}${glowShadow}`
  }
}

const HALO_OPACITY = [0, 0.45, 0.7, 0.88, 1]
const HALO_SCALE = [0.9, 1.12, 1.36, 1.62, 1.94]

const PILL_POSITIONS = [
  { left: '9%', top: '90%' },
  { left: '-4%', top: '28%' },
  { left: '50%', top: '-8%' },
  { left: '104%', top: '28%' },
  { left: '91%', top: '90%' }
]

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
  const arcDeg = (position / (DISTANCE_STEPS.length - 1)) * SWEEP
  const face = faceStyle(position, style)

  return (
    <div className="golden-knob-well">
      <div
        className="golden-knob-halo"
        aria-hidden="true"
        style={{
          opacity: HALO_OPACITY[position],
          transform: `scale(${HALO_SCALE[position]})`,
          animation:
            position >= 3
              ? position === 4
                ? 'gd-halo 1.8s ease-in-out infinite'
                : 'gd-halo 2.6s ease-in-out infinite'
              : 'none'
        }}
      />
      <div
        className="golden-knob-arc"
        aria-hidden="true"
        style={{ ['--gd-arc-deg' as string]: `${arcDeg}deg` }}
      />
      <div className="golden-knob-ticks" aria-hidden="true">
        {DISTANCE_STEPS.map((step, index) => {
          const tickAngle = -SWEEP / 2 + (index / (DISTANCE_STEPS.length - 1)) * SWEEP
          return <span key={step} style={{ transform: `rotate(${tickAngle}deg)` }} />
        })}
      </div>
      <div className="golden-knob-pills" aria-hidden="true">
        {STEP_LABELS.map((label, index) => (
          <span
            key={label}
            className="golden-knob-pill"
            data-active={index === position || undefined}
            style={PILL_POSITIONS[index]}
          >
            {label}
          </span>
        ))}
      </div>

      <button
        className="golden-knob"
        data-style={style}
        data-dragging={dragging || undefined}
        type="button"
        role="slider"
        aria-label={disabled ? 'Knob unavailable until context audio is resolved' : 'Distance'}
        aria-valuemin={1}
        aria-valuemax={DISTANCE_STEPS.length}
        aria-valuenow={position + 1}
        aria-valuetext={STEP_LABELS[position]}
        disabled={disabled}
        style={face}
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
        <span className="golden-knob__indicator" style={{ transform: `rotate(${angle}deg)` }} />
      </button>

      <div className="golden-knob-readout">
        <span className="golden-knob-label">{STEP_LABELS[position]}</span>
      </div>
    </div>
  )
}
