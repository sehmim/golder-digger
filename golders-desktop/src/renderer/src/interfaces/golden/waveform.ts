/**
 * Purely decorative bar heights for a result row. Seeded from the chunk id so
 * a given file always draws the same shape, but this is not derived from any
 * real audio -- there is no waveform data in the API response to show.
 */
const BAR_COUNT = 32

function hashSeed(id: string): number {
  let hash = 0
  for (let index = 0; index < id.length; index += 1) {
    hash = (hash * 31 + id.charCodeAt(index)) >>> 0
  }
  return hash
}

export function waveformHeights(id: string): number[] {
  const seed = hashSeed(id)
  const heights: number[] = []
  for (let bar = 0; bar < BAR_COUNT; bar += 1) {
    const n = Math.sin(seed * 0.0001 + bar * 12.9898) * 43758.5453
    const fraction = Math.abs(n - Math.floor(n))
    const envelope = Math.sin((bar / (BAR_COUNT - 1)) * Math.PI) * 0.6 + 0.4
    heights.push(Math.max(2, Math.round(fraction * envelope * 26)))
  }
  return heights
}
