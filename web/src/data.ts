/**
 * Data access for Phase 4: committed files only, no API.
 *
 * Phase 5 replaces the two loaders with fetches against /frames and /preview.
 * Every component takes data through these types, so the swap should not reach the UI.
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
  snr: number
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
  motion?: Motion
}

const BASE = import.meta.env.BASE_URL ?? '/'

export async function loadTargets(): Promise<Target[]> {
  const response = await fetch(`${BASE}data/targets.json`)
  if (!response.ok) throw new Error(`targets.json: HTTP ${response.status}`)
  const payload = (await response.json()) as { targets: Target[] }
  return payload.targets
}

/**
 * Returns null when a target has no committed sequence yet, which is the normal
 * state for four of the five targets while Phase 3 lands. Callers must render
 * that as "no sequence yet", never as an error.
 */
export async function loadSequence(slug: string, band: string): Promise<Sequence | null> {
  const response = await fetch(`${BASE}data/fallback/sequence/${slug}_${band}.json`)
  if (response.status === 404) return null
  if (!response.ok) throw new Error(`sequence ${slug}_${band}: HTTP ${response.status}`)
  return (await response.json()) as Sequence
}

export function frameUrl(frame: Frame): string {
  return `${BASE}data/fallback/sequence/${frame.file}`
}

export function sequenceUrl(slug: string, band: string): string {
  return `${BASE}data/fallback/sequence/${slug}_${band}.json`
}
