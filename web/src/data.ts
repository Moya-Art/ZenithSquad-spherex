/**
 * Data access: the live API first, committed files as the net.
 *
 * Phase 4 read `data/fallback/` directly, which is why the swap is confined to this file. Two
 * sources, one set of types: `/frames` returns the same manifest shape the committed JSON has, plus
 * a `url` per frame and the bands that coordinate actually has.
 *
 * The fallback is not decorative. It is what keeps the demo alive when IRSA or the API is having a
 * bad afternoon, so a failed request degrades to the committed R Draconis sequence rather than to an
 * error screen.
 */

export type Target = {
  slug: string
  name: string
  ra: number
  dec: number
  band: string
  pm_ra_cosdec: number
  pm_dec: number
  pm_source: string
  coordinate_note?: string
}

export type Measure = {
  x: number
  y: number
  flux: number
  flux_err: number
  snr: number | null
  wavelength_um?: number | null
}

export type Outlier = {
  mean: number | null
  median: number | null
  max_abs: number | null
}

export type Frame = {
  date: string
  t_min: number
  obs_id: string
  file: string
  bad_fraction: number
  outlier: Outlier
  measure: Measure | null
  /** Why a frame has no measurement: a saturated core, or a clipped cutout. */
  measure_skipped?: string | null
  /** Only on a live response: where to fetch this frame's WebP. */
  url?: string
}

export type Motion = {
  dx_arcsec: number
  dy_arcsec: number
  dt_years: number
  slope_arcsec_per_year: [number, number]
  slope_err: [number, number]
  rms_scatter_arcsec: [number, number]
  total_arcsec: number
  significant: boolean
  reliable?: boolean
}

export type Sequence = {
  target: string
  name: string
  band: string
  size_deg: number
  vmin: number
  vmax: number
  pixscale_arcsec: number
  generated_by: string
  note: string
  frames: Frame[]
  motion?: Motion | null
  /** 'live' when this came from the API; absent on committed files. */
  source?: 'live'
  /** A cached answer served because IRSA did not reply. */
  stale?: boolean
  available_bands?: Record<string, { frames: number; dates: number }>
  position_note?: string
}

const API = import.meta.env.VITE_API_URL ?? '/api'
const BASE = import.meta.env.BASE_URL ?? '/'

class ApiError extends Error {
  status: number | null

  constructor(message: string, status: number | null) {
    super(message)
    this.status = status
  }
}

async function getJson<T>(url: string): Promise<T> {
  let response: Response
  try {
    response = await fetch(url)
  } catch (error) {
    throw new ApiError(error instanceof Error ? error.message : String(error), null)
  }
  if (!response.ok) {
    throw new ApiError(`${url}: HTTP ${response.status}`, response.status)
  }
  return (await response.json()) as T
}

function absolute(path: string): string {
  return path.startsWith('http') ? path : `${API}${path}`
}

export async function loadTargets(): Promise<Target[]> {
  try {
    const payload = await getJson<{ targets: Target[] }>(`${API}/targets`)
    return payload.targets
  } catch {
    const payload = await getJson<{ targets: Target[] }>(`${BASE}data/targets.json`)
    return payload.targets
  }
}

/**
 * A sequence for one target and band, live when the API answers.
 *
 * Returns null when the pair genuinely has no sequence — the API says 404 (no coverage) or 422
 * (that band is not available), which is a state the UI renders as "no sequence yet", not as a
 * failure. Anything else — the API down, a 503 from IRSA — falls back to the committed file.
 */
export async function loadSequence(slug: string, band: string): Promise<Sequence | null> {
  try {
    const query = new URLSearchParams({ target: slug, band })
    return await getJson<Sequence>(`${API}/frames?${query.toString()}`)
  } catch (error) {
    const status = error instanceof ApiError ? error.status : null
    if (status === 404 || status === 422) return null
  }

  try {
    return await getJson<Sequence>(`${BASE}data/fallback/sequence/${slug}_${band}.json`)
  } catch (error) {
    const status = error instanceof ApiError ? error.status : null
    if (status === 404) return null
    throw error
  }
}

export function frameUrl(frame: Frame): string {
  if (frame.url) return absolute(frame.url)
  return `${BASE}data/fallback/sequence/${frame.file}`
}

export function sequenceUrl(slug: string, band: string): string {
  return `${BASE}data/fallback/sequence/${slug}_${band}.json`
}
