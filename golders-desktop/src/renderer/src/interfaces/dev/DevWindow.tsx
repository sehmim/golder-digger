import { useEffect, useState } from 'react'
import DevApp from './DevApp'
import type { DevSnapshot } from './types'

function isDevSnapshot(value: unknown): value is DevSnapshot {
  if (!value || typeof value !== 'object') return false
  const snapshot = value as Partial<DevSnapshot>
  return Boolean(snapshot.application && snapshot.interfaces?.goldDigger)
}

export default function DevWindow(): React.JSX.Element {
  const [snapshot, setSnapshot] = useState<DevSnapshot | null>(null)

  useEffect(() => {
    const accept = (next: unknown): void => {
      if (isDevSnapshot(next)) setSnapshot(next)
    }
    const off = window.desktop.onDevSnapshot(accept)
    void window.desktop.getDevSnapshot().then(accept)
    return off
  }, [])

  if (!snapshot) {
    return (
      <section className="dev-page" aria-label="Developer window">
        <div className="dev-page__canvas"><p className="dev-state-empty">Waiting for app state.</p></div>
      </section>
    )
  }

  return (
    <DevApp
      state={snapshot.application}
      goldDigger={snapshot.interfaces.goldDigger}
    />
  )
}
