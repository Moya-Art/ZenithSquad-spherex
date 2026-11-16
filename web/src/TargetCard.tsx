import { captionFor } from './captions'
import type { Target } from './data'

/**
 * What a named target is, in the pop-up.
 *
 * The pop-up is the only place a target's description lives now. It deliberately says what the object
 * is and what the catalogue says about it — never whether the sequence showed it moving: the motion
 * verdict left the UI on purpose, so no screen may imply it by other means.
 */

function properMotionMagnitude(target: Target): number {
  return Math.hypot(target.pm_ra_cosdec, target.pm_dec) / 1000
}

export function TargetCard({ target }: { target: Target }) {
  return (
    <div className="target-card">
      <p className="popover-caption">{captionFor(target.slug)}</p>

      <dl className="popover-facts">
        <div>
          <dt>RA</dt>
          <dd className="mono tnum">{target.ra.toFixed(5)}°</dd>
        </div>
        <div>
          <dt>Dec</dt>
          <dd className="mono tnum">
            {target.dec >= 0 ? '+' : ''}
            {target.dec.toFixed(5)}°
          </dd>
        </div>
        <div>
          <dt>Cat. proper motion</dt>
          <dd className="mono tnum">{properMotionMagnitude(target).toFixed(3)}″/yr</dd>
        </div>
      </dl>

      {target.coordinate_note && <p className="popover-note">{target.coordinate_note}</p>}
    </div>
  )
}
