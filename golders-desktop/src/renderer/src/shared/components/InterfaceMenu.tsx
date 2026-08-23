import { useEffect, useRef, useState } from 'react'
import { INTERFACES } from '../interfaceNavigation'
import type { InterfaceId } from '../interfaceNavigation'

interface InterfaceMenuProps {
  current: InterfaceId
  onNavigate: (destination: InterfaceId) => void
}

export default function InterfaceMenu({
  current,
  onNavigate
}: InterfaceMenuProps): React.JSX.Element {
  const [open, setOpen] = useState(false)
  const menu = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return

    const closeOnOutsideClick = (event: PointerEvent): void => {
      if (!menu.current?.contains(event.target as Node)) setOpen(false)
    }
    const closeOnEscape = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') setOpen(false)
    }

    window.addEventListener('pointerdown', closeOnOutsideClick)
    window.addEventListener('keydown', closeOnEscape)
    return () => {
      window.removeEventListener('pointerdown', closeOnOutsideClick)
      window.removeEventListener('keydown', closeOnEscape)
    }
  }, [open])

  return (
    <div className="interface-menu" ref={menu}>
      <button
        className="interface-menu__trigger"
        type="button"
        aria-label="Open interface menu"
        aria-expanded={open}
        aria-haspopup="menu"
        onClick={() => setOpen((currentOpen) => !currentOpen)}
      >
        <span />
        <span />
        <span />
      </button>

      {open ? (
        <div className="interface-menu__dropdown" role="menu">
          {INTERFACES.map((destination) => {
            const isCurrent = destination.id === current
            return (
              <button
                key={destination.id}
                type="button"
                role="menuitem"
                disabled={isCurrent}
                aria-current={isCurrent ? 'page' : undefined}
                onClick={() => {
                  setOpen(false)
                  onNavigate(destination.id)
                }}
              >
                {destination.label}
              </button>
            )
          })}
        </div>
      ) : null}
    </div>
  )
}
