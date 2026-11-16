import type { Target } from './data'

/**
 * Coordinates → named target.
 *
 * The pipeline centres each cutout on the exposure epoch using catalogue proper motion, so a
 * coordinate-only URL that failed to recover the target would open on empty sky: Barnard's Star is
 * 273.8″ from its J2000 position. The tolerance is the width of the spot the cache key rounds to
 * (1e-4° ≈ 0.36″), which is tight enough that no two of the five targets can be confused.
 */

export const TARGET_TOLERANCE_DEG = 1e-4

/** Shortest RA difference, in degrees, wrapped to (−180, 180]. */
function wrapRa(degrees: number): number {
  return ((degrees + 540) % 360) - 180
}

export function separationDeg(ra: number, dec: number, target: Target): number {
  const dra = wrapRa(target.ra - ra) * Math.cos((dec * Math.PI) / 180)
  const ddec = target.dec - dec
  return Math.hypot(dra, ddec)
}

export function resolveTarget(ra: number, dec: number, targets: Target[]): Target | null {
  let best: Target | null = null
  let bestSeparation = Infinity

  for (const target of targets) {
    const separation = separationDeg(ra, dec, target)
    if (separation < bestSeparation) {
      bestSeparation = separation
      best = target
    }
  }

  return bestSeparation <= TARGET_TOLERANCE_DEG ? best : null
}
