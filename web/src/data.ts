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
  /** The target core saturated, so only a lower flux bound exists. */
  saturated?: boolean
  /** The centroid fell back to the catalogue prediction rather than being measured. */
  centroid_from_prediction?: boolean
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

/**
 * Flux is in mJy and spans three orders of magnitude across the targets, so a fixed
 * number of decimals is wrong at one end or the other. Printing `12 ± 0` for an error
 * of 0.4 mJy claims a precision the measurement does not have.
 *
 * Decimals follow the magnitude of the value, with the same count used for the value
 * and its error so the two stay aligned.
 */
export function formatFlux(value: number, error?: number | null): string {
  const reference = Math.max(Math.abs(value), error != null ? Math.abs(error) : 0)
  const decimals = reference >= 100 ? 0 : reference >= 10 ? 1 : reference >= 1 ? 2 : 3
  const shown = value.toFixed(decimals)
  return error != null && Number.isFinite(error) ? `${shown} ± ${error.toFixed(decimals)}` : shown
}

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
  let apiError: unknown = null
  try {
    const query = new URLSearchParams({ target: slug, band })
    return await getJson<Sequence>(`${API}/frames?${query.toString()}`)
  } catch (error) {
    const status = error instanceof ApiError ? error.status : null
    if (status === 404 || status === 422) return null
    apiError = error
  }

  try {
    return await getJson<Sequence>(`${BASE}data/fallback/sequence/${slug}_${band}.json`)
  } catch (error) {
    const status = error instanceof ApiError ? error.status : null
    // No committed copy either. The API failure is the real story: reporting "no sequence yet"
    // here would blame a missing file for an archive that did not answer.
    if (status === 404) throw apiError ?? error
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

// --- the 102-band cube -------------------------------------------------------------------------

export type CubePlane = {
  index: number
  band: string
  detector: number
  channel: number
  wavelength_um: number
  bandwidth_um: number
  /** The dichroic channels (indices 50 and 51) carry no data by design. */
  blank: boolean
  coverage: number
  nan_pixels: number
  bytes: number
  file: string
  url?: string
}

export type CubeChannel = {
  channel: 'R' | 'G' | 'B'
  index: number
  band: string
  wavelength_um: number
}

export type CubeSpectrumPoint = {
  index: number
  flux_mjy: number | null
  noise_mjy: number | null
  annulus_clipped: boolean
}

export type CubeProgress = {
  planes_done: number
  planes_total: number | null
  bytes_done: number | null
  bytes_total: number | null
  started_at: string | null
  updated_at: string | null
  eta_seconds: number | null
}

/**
 * Either a finished cube or the state of the build that will produce one. A build is reported with
 * the planes that already exist, which is what lets the viewer open before plane 102 lands.
 */
export type Cube = {
  state: 'ready' | 'queued' | 'building' | 'failed'
  source?: 'committed' | 'hit'
  target: string
  name: string
  ra: number
  dec: number
  size_deg: number
  crop_px?: number
  crop_arcmin?: number
  pixscale_arcsec?: number
  target_xy?: [number, number]
  tile?: {
    norder: number
    ipix: number
    dirid: number
    version: string
    url: string
    bytes: number | null
    shape: [number, number]
    crop: [number, number, number, number]
    mosaic_epoch: number
  }
  stretch?: { mode: string; vmin: number; vmax: number }
  planes: CubePlane[]
  composite?: {
    file: string
    url?: string
    bytes: number
    channels: CubeChannel[]
    note?: string
  } | null
  spectrum?: { unit: string; points: CubeSpectrumPoint[] }
  depth?: number
  blank_planes?: number[]
  notes?: Record<string, string>
  message?: string
  progress?: CubeProgress
  error?: { reason: string; detail: string }
  keeps_running?: boolean
  retry_with_refresh?: boolean
}

export type CubeRequest = {
  target?: string
  ra?: number
  dec?: number
  size?: number
  refresh?: boolean
}

/**
 * One request that answers with either the cube or the build's progress.
 *
 * A 501 or a network failure falls back to the committed artifact, so a demo survives the API being
 * down; a 404 is not "missing" here, because a cube is never legitimately absent for a coordinate
 * the archive covers.
 */
export async function loadCube(request: CubeRequest): Promise<Cube | null> {
  const query = new URLSearchParams()
  if (request.target) query.set('target', request.target)
  if (request.ra != null && request.dec != null) {
    query.set('ra', String(request.ra))
    query.set('dec', String(request.dec))
  }
  if (request.size != null) query.set('size', String(request.size))
  if (request.refresh) query.set('refresh', 'true')

  let apiError: unknown = null
  try {
    return await getJson<Cube>(`${API}/cube?${query.toString()}`)
  } catch (error) {
    apiError = error
  }

  if (request.target) {
    try {
      return await getJson<Cube>(`${BASE}data/fallback/cube/${request.target}.json`)
    } catch {
      // Fall through: report the API's failure, which is the real story.
    }
  }
  throw apiError ?? new Error('cube unavailable')
}

export function cubePlaneUrl(plane: CubePlane): string {
  if (plane.url) return absolute(plane.url)
  return `${BASE}data/fallback/cube/${plane.file}`
}

export function cubeCompositeUrl(cube: Cube): string | null {
  if (!cube.composite) return null
  if (cube.composite.url) return absolute(cube.composite.url)
  return `${BASE}data/fallback/cube/${cube.composite.file}`
}
