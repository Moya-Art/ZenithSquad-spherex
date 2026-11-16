/**
 * URL state: `?ra=248.16775&dec=66.75497` and nothing else.
 *
 * A coordinate is the only shareable state. A band, an epoch, a mode or a palette describe a view of
 * one particular frame list, and a link that carries them stops meaning what it said once the list
 * changes. Five decimals is 0.036″, the rounding the cache key uses, so a shared link and the request
 * it triggers always agree on the same cache entry.
 *
 * An out-of-range coordinate is rejected here, before any request is made: `?ra=999` is a typo, not a
 * patch of sky.
 */

export type Position = { ra: number; dec: number }

/** R Draconis: the first row of `data/targets.json`, so the default page is a real target. */
export const DEFAULT_POSITION: Position = { ra: 248.16775, dec: 66.75497 }

export const URL_DECIMALS = 5

export type ParsedViewState =
  | { position: Position; invalid: false }
  | { position: null; invalid: true }

export function isValidCoordinate(ra: number, dec: number): boolean {
  return Number.isFinite(ra) && Number.isFinite(dec) && ra >= 0 && ra < 360 && dec >= -90 && dec <= 90
}

function parseDegrees(value: string): number | null {
  if (!value.trim()) return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

export function parseViewState(search: string): ParsedViewState {
  const params = new URLSearchParams(search)
  const rawRa = params.get('ra')
  const rawDec = params.get('dec')

  // Nothing in the URL: start on the default target.
  if (rawRa == null && rawDec == null) {
    return { position: DEFAULT_POSITION, invalid: false }
  }

  // Half a coordinate is not a coordinate.
  if (rawRa == null || rawDec == null) {
    return { position: null, invalid: true }
  }

  const ra = parseDegrees(rawRa)
  const dec = parseDegrees(rawDec)
  if (ra == null || dec == null || !isValidCoordinate(ra, dec)) {
    return { position: null, invalid: true }
  }

  return { position: { ra, dec }, invalid: false }
}

export function serializeViewState(position: Position): string {
  const params = new URLSearchParams()
  params.set('ra', position.ra.toFixed(URL_DECIMALS))
  params.set('dec', position.dec.toFixed(URL_DECIMALS))
  return `?${params.toString()}`
}

export function readViewState(): ParsedViewState {
  return parseViewState(window.location.search)
}

export function writeViewState(position: Position): void {
  const next = `${window.location.pathname}${serializeViewState(position)}`
  window.history.replaceState(null, '', next)
}
