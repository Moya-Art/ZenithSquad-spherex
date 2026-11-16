import { CubeView } from './CubeView'
import { LoadingNotice } from './LoadingNotice'
import type { PaletteEntry } from './colormaps'
import type { Cube } from './data'

/**
 * The wavelength plate, on the right.
 *
 * It loads on demand: a cold patch of sky costs one 306 MiB all-sky tile, and paying that for every
 * visit would be minutes of build for a page someone may only want to blink. A committed cube is
 * free, so it appears without the button.
 */

type Props = {
  label: string
  cube: Cube | null
  loading: boolean
  error: string | null
  requested: boolean
  request: () => void
  retry: () => void
  plane: number
  setPlane: (index: number) => void
  palette: PaletteEntry
  disabled: boolean
}

function captionForCube(cube: Cube | null): string {
  if (!cube || cube.planes.length === 0) return 'loads on demand'
  const field = cube.crop_arcmin ? `${cube.crop_arcmin}′` : `${cube.size_deg}°`
  const scale = cube.pixscale_arcsec ? ` · ${cube.pixscale_arcsec.toFixed(2)}″/px` : ''
  return `${cube.planes.length} planes · ${field}${scale}`
}

export function WavelengthPlate({
  label,
  cube,
  loading,
  error,
  requested,
  request,
  retry,
  plane,
  setPlane,
  palette,
  disabled,
}: Props) {
  return (
    <section className="plate plate--wavelength">
      <div className="plate-head">
        <span className="plate-title">The wavelength</span>
        <span className="plate-caption mono tnum">{captionForCube(cube)}</span>
      </div>

      {disabled && (
        <div className="plate-state">
          <div className="plate-state-title">Enter a coordinate</div>
          <div className="plate-state-body">
            The spectrum of a patch of sky loads with its coordinate.
          </div>
        </div>
      )}

      {!disabled && !requested && (
        <div className="plate-state plate-state--decision">
          <div className="plate-state-title">102 wavelengths of {label}</div>
          <div className="plate-state-body">
            This patch needs one 306 MB all-sky tile. It is downloaded once, and the raw tile is
            deleted as soon as the planes are rendered.
          </div>
          <button type="button" className="notice-action" onClick={request}>
            Load the 102 wavelengths
          </button>
        </div>
      )}

      {!disabled && requested && loading && <LoadingNotice kind="cube" targetName={label} />}

      {!disabled && requested && error && !cube && (
        <div className="notice notice--bad">
          <div className="notice-title">The wavelength plate did not load</div>
          <div className="notice-body mono">{error}</div>
          <button type="button" className="notice-action" onClick={retry}>
            Try again
          </button>
        </div>
      )}

      {!disabled && cube && (
        <CubeView
          cube={cube}
          plane={plane}
          onPlane={setPlane}
          palette={palette}
          onRetry={retry}
        />
      )}
    </section>
  )
}
