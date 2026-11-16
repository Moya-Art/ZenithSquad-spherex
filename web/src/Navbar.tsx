import { useCallback, useEffect, useState } from 'react'

import { CoordinateInput } from './CoordinateInput'
import { Popover } from './Popover'
import { QueuePopover } from './QueuePopover'
import { TargetsPopover } from './TargetsPopover'
import { loadQueue, type QueueJob, type Target } from './data'

/**
 * Navigation and the only two pop-over menus.
 *
 * The coordinate fields are the primary way to move: they are always visible, they validate on their
 * own, and they write the URL. `Targets` is the shortcut list and `Queue` reports builds that keep
 * running on the server after you navigate away, so the badge is the difference between "my build is
 * gone" and "my build is progressing".
 */

type Props = {
  targets: Target[]
  targetsError: string | null
  current: Target | null
  ra: string
  dec: string
  errors: { ra?: string; dec?: string } | null
  busy: boolean
  onRaChange: (value: string) => void
  onDecChange: (value: string) => void
  onSubmit: () => void
  onPick: (target: Target) => void
}

type Menu = 'targets' | 'queue' | null

const POLL_MS = 2000

export function Navbar({
  targets,
  targetsError,
  current,
  ra,
  dec,
  errors,
  busy,
  onRaChange,
  onDecChange,
  onSubmit,
  onPick,
}: Props) {
  const [menu, setMenu] = useState<Menu>(null)
  const [jobs, setJobs] = useState<QueueJob[] | null>(null)
  const [queueError, setQueueError] = useState<string | null>(null)

  const close = useCallback(() => setMenu(null), [])

  // A snapshot on mount keeps the badge honest without polling; while the panel is open the queue is
  // refreshed on a timer, which is the only moment its detail is on screen.
  useEffect(() => {
    let cancelled = false

    const refresh = () => {
      loadQueue()
        .then((list) => {
          if (cancelled) return
          setJobs(list)
          setQueueError(null)
        })
        .catch((failure: Error) => {
          if (cancelled) return
          // Never invent a count the API did not give.
          setQueueError(failure.message)
        })
    }

    void refresh()
    if (menu !== 'queue') return () => { cancelled = true }

    const timer = window.setInterval(refresh, POLL_MS)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [menu])

  const running = jobs?.filter((job) => job.state === 'queued' || job.state === 'building').length ?? 0

  return (
    <header className="navbar">
      <div className="brand">
        <img className="brand-logo" src="/space-apps-logo.png" alt="NASA Space Apps Challenge" />
        <span className="brand-divider" aria-hidden="true" />
        <span className="brand-name">SPHEREx Sky-Time</span>
      </div>

      <CoordinateInput
        ra={ra}
        dec={dec}
        onRaChange={onRaChange}
        onDecChange={onDecChange}
        onSubmit={onSubmit}
        errors={errors}
        busy={busy}
      />

      <div className="nav-actions">
        <div className="nav-menu" data-popover-root>
          <button
            type="button"
            className={`nav-btn ${menu === 'targets' ? 'is-open' : ''}`}
            onClick={() => setMenu((value) => (value === 'targets' ? null : 'targets'))}
            aria-expanded={menu === 'targets'}
            aria-haspopup="dialog"
          >
            Targets
            <span className="nav-caret" aria-hidden="true">
              ▾
            </span>
          </button>
          <Popover open={menu === 'targets'} onClose={close} label="Targets">
            <TargetsPopover
              targets={targets}
              error={targetsError}
              current={current}
              onPick={(target) => {
                onPick(target)
                close()
              }}
            />
          </Popover>
        </div>

        <div className="nav-menu" data-popover-root>
          <button
            type="button"
            className={`nav-btn ${menu === 'queue' ? 'is-open' : ''}`}
            onClick={() => setMenu((value) => (value === 'queue' ? null : 'queue'))}
            aria-expanded={menu === 'queue'}
            aria-haspopup="dialog"
          >
            Queue
            {running > 0 && <span className="nav-badge mono tnum">{running}</span>}
          </button>
          <Popover open={menu === 'queue'} onClose={close} label="Queued builds">
            <QueuePopover jobs={jobs} error={queueError} />
          </Popover>
        </div>
      </div>
    </header>
  )
}
