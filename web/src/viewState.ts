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
 *
 * Moving to a coordinate is a navigation, so it pushes an entry: Back has to return to the patch of
 * sky you were looking at. Correcting the bar — filling in the default, rounding, throwing away a
 * coordinate that was never valid — is not a navigation, so it replaces, and Back never lands on an
 * address the page refused to show.
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

/** The precision the cache key rounds to; a coordinate is only ever this specific. */
function roundDegrees(value: number): number {
  return Number(value.toFixed(URL_DECIMALS))
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

  const parsedRa = parseDegrees(rawRa)
  const parsedDec = parseDegrees(rawDec)
  if (parsedRa == null || parsedDec == null) {
    return { position: null, invalid: true }
  }

  // Rounded before the range check, not after: `359.999996` becomes `360.00000`, which the API
  // rejects, and it must be rejected here too rather than sent and bounced.
  const ra = roundDegrees(parsedRa)
  const dec = roundDegrees(parsedDec)
  if (!isValidCoordinate(ra, dec)) {
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

/**
 * What the bar should say for a search string, and whether it needs saying at all.
 *
 * Three cases, and the address bar is never allowed to claim a different patch of sky than the one
 * on screen:
 * - a coordinate was asked for: it is used, and normalized to five decimals;
 * - nothing was asked for: the default target is used, and the bar is filled in so a copied link
 *   points at what the visitor is actually looking at;
 * - the coordinate was unusable: there is no position, and the query is stripped rather than left
 *   behind as a broken address that survives a reload and a share.
 */
export type CanonicalViewState = {
  position: Position | null
  /** The query to write — `''` to strip it — or null when the bar already says it. */
  url: string | null
  /** The search string that came in was not a usable coordinate. */
  repaired: boolean
}

export function canonicalViewState(search: string): CanonicalViewState {
  const parsed = parseViewState(search)

  if (parsed.invalid) {
    return { position: null, url: search === '' ? null : '', repaired: true }
  }

  const url = serializeViewState(parsed.position)
  return { position: parsed.position, url: url === search ? null : url, repaired: false }
}

/**
 * Write the address bar. Pushes by default, because a coordinate is a place; `replace` is for
 * corrections, where adding a history entry would make Back step onto an address nobody visited.
 */
export function writeViewState(
  position: Position | null,
  options: { replace?: boolean } = {},
): void {
  const query = position ? serializeViewState(position) : ''
  const next = `${window.location.pathname}${query}`
  if (options.replace) window.history.replaceState(null, '', next)
  else window.history.pushState(null, '', next)
}
