/**
 * The colour adjustment shared by both plates and the sidebar.
 *
 * Three independent passes, applied in this order:
 *
 * 1. `r`/`g`/`b` — per-channel gains, 255 = neutral.
 * 2. `background`/`highlight` — a two-point map: the colour value 0 becomes and the colour value 255
 *    becomes. Black/white is the identity, so a warm background can replace the black without
 *    touching the bright structure.
 * 3. `threshold` — paints pixels by their original greyscale level. `above` paints the bright side,
 *    `below` the faint side; `softness` feathers the edge and colour is exact at full weight.
 *
 * The threshold reads the greyscale frame, not the palette result, so "level 120 and up" means the
 * same thing whatever ramp is showing.
 */

export type ThresholdMode = 'above' | 'below'

export type Threshold = {
  enabled: boolean
  mode: ThresholdMode
  /** Greyscale level, 0–255. */
  level: number
  /** Half-width of the transition, 0 = a hard cut. */
  softness: number
  color: string
}

export type Tint = {
  r: number
  g: number
  b: number
  background: string
  highlight: string
  threshold: Threshold
}

export const NEUTRAL_THRESHOLD: Threshold = {
  enabled: false,
  mode: 'above',
  level: 96,
  softness: 8,
  color: '#ffd166',
}

export const NEUTRAL_TINT: Tint = {
  r: 255,
  g: 255,
  b: 255,
  background: '#000000',
  highlight: '#ffffff',
  threshold: NEUTRAL_THRESHOLD,
}

export function isNeutralMap(tint: Tint): boolean {
  return (
    tint.r === 255 &&
    tint.g === 255 &&
    tint.b === 255 &&
    tint.background.toLowerCase() === NEUTRAL_TINT.background &&
    tint.highlight.toLowerCase() === NEUTRAL_TINT.highlight
  )
}

export function isNeutralTint(tint: Tint): boolean {
  return isNeutralMap(tint) && !tint.threshold.enabled
}

export function parseHex(hex: string): [number, number, number] {
  const value = Number.parseInt(hex.replace('#', ''), 16)
  if (!Number.isFinite(value)) return [0, 0, 0]
  return [(value >> 16) & 255, (value >> 8) & 255, value & 255]
}
