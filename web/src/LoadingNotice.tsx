import { useEffect, useState } from 'react'

/**
 * What the app shows while a live sequence is being built.
 *
 * A cold `/frames` downloads one cutout per observing date from IRSA, so it takes tens of seconds
 * and can take minutes if the archive is slow. "loading sequence…" gave no way to tell a slow build
 * from a hang, and no idea what was happening. This says what the work is, shows that it is still
 * moving, and stops claiming a duration it cannot know.
 */
type Props = {
  targetName: string | null
}

export function LoadingNotice({ targetName }: Props) {
  const [seconds, setSeconds] = useState(0)

  // Only setState inside the interval, never in the effect body: the counter belongs to the wait.
  useEffect(() => {
    const timer = setInterval(() => setSeconds((current) => current + 1), 1000)
    return () => clearInterval(timer)
  }, [])

  const subject = targetName ?? 'this patch of sky'

  return (
    <div className="notice" role="status" aria-live="polite">
      <div className="notice-title">Building {subject} from the NASA archive</div>
      <div className="notice-body">
        {seconds < 3
          ? 'Asking IRSA which dates this patch of sky was observed…'
          : 'The first visit to a coordinate downloads one image per observing date and renders them all against a single brightness scale. Usually 30–60 seconds; returns here are instant.'}
        <div className="notice-elapsed mono tnum">{seconds}s elapsed</div>
      </div>
    </div>
  )
}
