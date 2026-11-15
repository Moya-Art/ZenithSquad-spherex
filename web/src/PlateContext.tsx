import { captionFor } from './captions'
import type { Motion, Sequence, Target } from './data'

/**
 * Target context, beside the image.
 *
 * The inspector answers "what did this frame measure". This answers "what am I
 * looking at, and what does the whole sequence say" — statements about the target
 * across all epochs, kept separate so a per-frame reading never gets mixed in.
 *
 * A motion result consistent with zero is stated as exactly that. The endpoints of
 * a variable star's centroid always differ; dressing that up as motion is the
 * mistake this block exists to prevent.
 */

type Props = {
  target: Target
  sequence: Sequence
  motion?: Motion
}

function properMotionMagnitude(target: Target): number {
  return Math.hypot(target.pm_ra_cosdec, target.pm_dec) / 1000
}

export function PlateContext({ target, sequence, motion }: Props) {
  // What the whole sequence says, not what one epoch says. A star that varies is
  // described by its extremes and when they happened, not by a single frame's flux.
  const measured = sequence.frames.filter(
    (frame) => frame.measure && Number.isFinite(frame.measure.flux),
  )
  const brightest = measured.reduce<(typeof measured)[number] | null>(
    (best, frame) =>
      !best || (frame.measure?.flux ?? -Infinity) > (best.measure?.flux ?? -Infinity) ? frame : best,
    null,
  )
  const dimmest = measured.reduce<(typeof measured)[number] | null>(
    (worst, frame) =>
      !worst || (frame.measure?.flux ?? Infinity) < (worst.measure?.flux ?? Infinity)
        ? frame
        : worst,
    null,
  )

  const peak = brightest?.measure?.flux ?? null
  const trough = dimmest?.measure?.flux ?? null
  const amplitude = peak !== null && trough !== null && trough > 0 ? peak / trough : null

  return (
    <div className="context">
      <p className="context-caption">{captionFor(target.slug)}</p>

      {amplitude !== null && brightest && dimmest && (
        <div className="context-span">
          <div className="context-label">Across the sequence</div>
          <div className="context-verdict">
            {amplitude >= 1.5 ? `varies ${amplitude.toFixed(1)}×` : 'stable within noise'}
          </div>
          <div className="context-note">
            Peaks at {peak?.toFixed(0)} on {brightest.date}, falls to {trough?.toFixed(0)} on{' '}
            {dimmest.date}. Same stretch applied to every frame, so the change is in the sky, not
            the display.
          </div>
        </div>
      )}

      <dl className="context-facts">
        <div>
          <dt>RA</dt>
          <dd className="mono tnum">{target.ra.toFixed(4)}°</dd>
        </div>
        <div>
          <dt>Dec</dt>
          <dd className="mono tnum">
            {target.dec >= 0 ? '+' : ''}
            {target.dec.toFixed(4)}°
          </dd>
        </div>
        <div>
          <dt>Cat. proper motion</dt>
          <dd className="mono tnum">{properMotionMagnitude(target).toFixed(3)}″/yr</dd>
        </div>
        <div>
          <dt>Band · field</dt>
          <dd className="mono">
            {sequence.band} · {sequence.size_deg}°
          </dd>
        </div>
      </dl>

      {motion && (
        <div className="context-motion">
          <div className="context-label">Centroid motion</div>

          {motion.significant ? (
            <>
              <div className="context-verdict is-real">
                moved {motion.total_arcsec.toFixed(1)}″ over {motion.dt_years.toFixed(2)} yr
              </div>
              <div className="context-note">
                Fitted rate {Math.hypot(...motion.slope_arcsec_per_year).toFixed(2)} ±{' '}
                {Math.hypot(...motion.slope_err).toFixed(2)}″/yr, larger than the scatter
                ({Math.max(...motion.rms_scatter_arcsec).toFixed(1)}″). Consistent with real
                motion across the sky.
              </div>
            </>
          ) : (
            <>
              <div className="context-verdict">consistent with zero</div>
              <div className="context-note">
                The first and last centroids differ by {motion.total_arcsec.toFixed(1)}″, but the
                fitted rate is {Math.hypot(...motion.slope_arcsec_per_year).toFixed(2)} ±{' '}
                {Math.hypot(...motion.slope_err).toFixed(2)}″/yr and the centroid wanders
                (±{Math.max(...motion.rms_scatter_arcsec).toFixed(1)}″). That is a variable core,
                not motion.
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}
