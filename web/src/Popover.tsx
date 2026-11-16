import { useEffect, type ReactNode } from 'react'

/**
 * The shared pop-over shell.
 *
 * The trigger lives inside the same `data-popover-root` wrapper, so clicking the button that opened a
 * panel closes it instead of closing and immediately reopening it. Only one panel is open at a time,
 * which `Navbar` enforces; nothing here dims the page or traps focus, because the coordinate fields
 * must stay reachable while a panel is open.
 */

type Props = {
  open: boolean
  onClose: () => void
  label: string
  children: ReactNode
}

export function Popover({ open, onClose, label, children }: Props) {
  useEffect(() => {
    if (!open) return

    const onPointer = (event: PointerEvent) => {
      const target = event.target
      if (target instanceof Element && target.closest('[data-popover-root]')) return
      onClose()
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }

    document.addEventListener('pointerdown', onPointer)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onPointer)
      document.removeEventListener('keydown', onKey)
    }
  }, [open, onClose])

  if (!open) return null

  return (
    <div className="popover" role="dialog" aria-label={label}>
      {children}
    </div>
  )
}
