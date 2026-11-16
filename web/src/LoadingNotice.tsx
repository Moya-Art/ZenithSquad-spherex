import { useEffect, useState } from 'react'

/**
 * What a plate shows while its build runs.
 *
 * Each plate explains its own work: a date sequence is a cutout per observing date, a wavelength
 * plate is one large all-sky tile. Keeping one message for both meant the cube path claimed a
 * duration it could not honour, so `kind` is not cosmetic.
 */

type Props = {
  kind: 'sequence' | 'cube'
  targetName: string | null
}

export function LoadingNotice({ kind, targetName }: Props) {
  const [seconds, setSeconds] = useState(0)

  // Only setState inside the interval, never in the effect body: the counter belongs to the wait.
  useEffect(() => {
    const timer = setInterval(() => setSeconds((current) => current + 1), 1000)
    return () => clearInterval(timer)
  }, [])

  const subject = targetName ?? 'this patch of sky'

  return (
    <div className="notice" role="status" aria-live="polite">
      <div className="notice-title">
        {kind === 'sequence'
          ? `Building ${subject} from the NASA archive`
          : `Measuring the 102 wavelengths of ${subject}`}
      </div>
      <div className="notice-body">
        {kind === 'sequence'
          ? seconds < 3
            ? 'Asking IRSA which dates this patch of sky was observed…'
            : 'The first visit to a coordinate downloads one image per observing date and renders them all against a single brightness scale. Returns here are instant.'
          : seconds < 3
            ? 'Fetching one all-sky tile and cropping it to this coordinate…'
            : 'This patch needs one 306 MB all-sky tile. It is charged once per patch of sky, and the raw tile is deleted once the planes are rendered.'}
        <div className="notice-elapsed mono tnum">{seconds}s elapsed</div>
      </div>
    </div>
  )
}
