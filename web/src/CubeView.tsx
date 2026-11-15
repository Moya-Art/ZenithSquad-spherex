/**
 * Spectrum mode: the 102 wavelength planes of one patch of sky, plus a spectrum and a false-colour
 * composite of three of them.
 *
 * The planes are greyscale WebP and the colormap is applied here, in a canvas, to the pixels that
 * were already downloaded. That is why eleven palettes cost nothing: a palette is a 256-entry table
 * and a pass over a 160x160 buffer, not another image.
 *
 * While a build runs the page fills in: the planes that exist are fetched and drawn, the spectrum
 * fills left to right, and the progress strip says what is happening and how long it should take.
 */

import { useEffect, useMemo, useRef, useState } from 'react'

import { SpectrumChart } from './SpectrumChart'
import { COLORMAPS, applyLut, buildLut, randomColormap, type Colormap } from './colormaps'
import { cubeCompositeUrl, cubePlaneUrl, type Cube, type CubePlane } from './data'

type Props = {
  cube: Cube
  plane: number
  onPlane: (index: number) => void
  colormap: Colormap
  onColormap: (colormap: Colormap) => void
  onRetry: () => void
}

async function decodePlane(src: string): Promise<ImageData> {
  const response = await fetch(src)
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  const bitmap = await createImageBitmap(await response.blob())
  const canvas = document.createElement('canvas')
  canvas.width = bitmap.width
  canvas.height = bitmap.height
  const context = canvas.getContext('2d')
  if (!context) throw new Error('no 2d context')
  context.drawImage(bitmap, 0, 0)
  bitmap.close()
  return context.getImageData(0, 0, canvas.width, canvas.height)
}

function thumbnail(grey: ImageData, lut: Uint8Array, size: number): ImageData {
  const out = new ImageData(size, size)
  for (let y = 0; y < size; y += 1) {
    const sourceY = Math.min(Math.floor((y * grey.height) / size), grey.height - 1)
    for (let x = 0; x < size; x += 1) {
      const sourceX = Math.min(Math.floor((x * grey.width) / size), grey.width - 1)
      const value = grey.data[(sourceY * grey.width + sourceX) * 4]
      const target = (y * size + x) * 4
      const lutIndex = value * 3
      out.data[target] = lut[lutIndex]
      out.data[target + 1] = lut[lutIndex + 1]
      out.data[target + 2] = lut[lutIndex + 2]
      out.data[target + 3] = 255
    }
  }
  return out
}

function Swatch({
  grey,
  colormap,
  selected,
  onPick,
}: {
  grey: ImageData | null
  colormap: Colormap
  selected: boolean
  onPick: () => void
}) {
  const ref = useRef<HTMLCanvasElement | null>(null)

  useEffect(() => {
    const canvas = ref.current
    if (!canvas || !grey) return
    const size = 40
    const image = thumbnail(grey, buildLut(colormap), size)
    canvas.width = size
    canvas.height = size
    canvas.getContext('2d')?.putImageData(image, 0, 0)
  }, [grey, colormap])

  return (
    <button
      type="button"
      className={`swatch ${selected ? 'is-active' : ''}`}
      onClick={onPick}
      aria-pressed={selected}
      title={colormap.name}
    >
      <canvas ref={ref} className="swatch-canvas" />
      <span className="swatch-name mono">{colormap.name}</span>
    </button>
  )
}

/**
 * Seconds since the build started, updated once a second.
 *
 * The clock is read inside the interval, never during render: `Date.now()` in a render is an impure
 * call that makes the output depend on when React happened to re-render.
 */
function useElapsed(startedAt: string | null | undefined, active: boolean): number | null {
  const [elapsed, setElapsed] = useState<number | null>(null)
  useEffect(() => {
    if (!active || !startedAt) return
    const start = Date.parse(startedAt)
    if (Number.isNaN(start)) return
    const timer = window.setInterval(
      () => setElapsed(Math.max(0, Math.round((Date.now() - start) / 1000))),
      1000,
    )
    return () => window.clearInterval(timer)
  }, [startedAt, active])
  return elapsed
}

function ProgressStrip({ cube }: { cube: Cube }) {
  const progress = cube.progress
  const running = cube.state === 'building' || cube.state === 'queued'
  const elapsed = useElapsed(progress?.started_at, running)
  const done = progress?.planes_done ?? 0
  const total = progress?.planes_total ?? null

  const percent = (() => {
    if (progress?.bytes_total && progress.bytes_done != null) {
      return Math.min(100, Math.round((progress.bytes_done / progress.bytes_total) * 100))
    }
    if (total) return Math.min(100, Math.round((done / total) * 100))
    return null
  })()

  return (
    <div className="build-strip" role="status" aria-live="polite">
      <div className="build-line">
        <span className="build-title">
          {cube.state === 'queued' ? 'Queued' : cube.message ?? 'Building'}
        </span>
        {percent != null && <span className="build-percent mono tnum">{percent}%</span>}
      </div>
      <div className="build-bar" aria-hidden="true">
        <span style={{ width: `${percent ?? 4}%` }} />
      </div>
      <div className="build-meta mono tnum">
        {progress?.bytes_total
          ? `${((progress.bytes_done ?? 0) / 1e6).toFixed(0)} / ${(
              progress.bytes_total / 1e6
            ).toFixed(0)} MB`
          : null}
        {total ? ` · planes ${done}/${total}` : null}
        {progress?.eta_seconds != null ? ` · about ${progress.eta_seconds}s left` : null}
        {elapsed != null ? ` · ${elapsed}s elapsed` : null}
      </div>
      <div className="build-note">
        This keeps running on the server if you close the tab, and the finished cube is kept for
        everyone who looks at the same patch of sky.
      </div>
    </div>
  )
}

export function CubeView({ cube, plane, onPlane, colormap, onColormap, onRetry }: Props) {
  const cache = useRef(new Map<number, ImageData>())
  const [loaded, setLoaded] = useState(0)
  const alive = useRef(true)

  const signature = useMemo(
    () => cube.planes.map((entry) => entry.index).join(','),
    [cube.planes],
  )

  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    const run = async () => {
      for (const entry of cube.planes) {
        if (cancelled || !alive.current) return
        if (cache.current.has(entry.index)) continue
        try {
          cache.current.set(entry.index, await decodePlane(cubePlaneUrl(entry)))
        } catch {
          // A plane that will not decode is a hole in the scrubber, not a broken page.
        }
        if (!cancelled) setLoaded(cache.current.size)
      }
    }
    void run()
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signature])

  const available = cube.planes
  const selected: CubePlane | null =
    available.find((entry) => entry.index === plane) ?? available[0] ?? null
  const position = selected
    ? available.findIndex((entry) => entry.index === selected.index)
    : -1
  const grey = selected ? cache.current.get(selected.index) ?? null : null
  const compositeUrl = cubeCompositeUrl(cube)

  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || !grey) return
    canvas.width = grey.width
    canvas.height = grey.height
    const context = canvas.getContext('2d')
    if (!context) return
    const recoloured = new ImageData(
      new Uint8ClampedArray(grey.data),
      grey.width,
      grey.height,
    )
    applyLut(recoloured.data, buildLut(colormap))
    context.putImageData(recoloured, 0, 0)
  }, [grey, colormap, loaded])

  const step = (delta: number) => {
    if (position < 0) return
    const next = available[position + delta]
    if (next) onPlane(next.index)
  }

  return (
    <div className="cube">
      <div className="cube-head">
        <span className="plate-name">{cube.name}</span>
        <span className="plate-meta mono tnum">
          {cube.crop_arcmin ? `${cube.crop_arcmin}′ field · ` : ''}
          {cube.pixscale_arcsec ? `${cube.pixscale_arcsec.toFixed(2)}″/px · ` : ''}
          {available.length} planes
          {cube.tile ? ` · ${cube.tile.version}` : ''}
        </span>
      </div>

      {(cube.state === 'building' || cube.state === 'queued') && <ProgressStrip cube={cube} />}

      {cube.state === 'failed' && (
        <div className="notice notice--bad">
          <div className="notice-title">This patch of sky could not be built</div>
          <div className="notice-body mono">{cube.error?.detail ?? cube.message}</div>
          <button type="button" className="notice-action" onClick={onRetry}>
            Try again
          </button>
        </div>
      )}

      {available.length > 0 && (
        <>
          <div className="cube-body">
            <div className="cube-stage">
              <div className="frame">
                <canvas
                  ref={canvasRef}
                  className="frame-canvas"
                  style={{ imageRendering: 'pixelated' }}
                  aria-label={
                    selected
                      ? `${cube.name} at ${selected.wavelength_um.toFixed(3)} micrometres`
                      : cube.name
                  }
                />
                {!grey && (
                  <span className="frame-badge">
                    loading plane {position + 1}/{available.length}
                  </span>
                )}
                {selected?.blank && (
                  <span className="frame-badge frame-badge--bad">
                    blank by design — dichroic channel
                  </span>
                )}
              </div>

              <div className="transport">
                <button
                  type="button"
                  className="transport-btn"
                  onClick={() => step(-1)}
                  aria-label="previous wavelength"
                >
                  ‹
                </button>
                <button
                  type="button"
                  className="transport-btn"
                  onClick={() => step(1)}
                  aria-label="next wavelength"
                >
                  ›
                </button>
                <span className="transport-counter mono tnum">
                  {selected ? selected.band : '—'}
                  <span className="transport-total">
                    {' '}
                    ch {selected ? String(selected.channel).padStart(2, '0') : '—'}
                  </span>
                </span>
                <input
                  className="plane-slider"
                  type="range"
                  min={0}
                  max={Math.max(available.length - 1, 0)}
                  value={position < 0 ? 0 : position}
                  onChange={(event) => {
                    const next = available[Number(event.target.value)]
                    if (next) onPlane(next.index)
                  }}
                  aria-label="wavelength plane"
                />
                <span className="hint mono tnum">
                  {selected ? `${selected.wavelength_um.toFixed(3)} µm` : ''}
                </span>
              </div>
            </div>

            <div className="cube-side">
              {compositeUrl && cube.composite && (
                <figure className="composite">
                  <img src={compositeUrl} alt={`${cube.name} in three SPHEREx bands`} />
                  <figcaption className="composite-bands mono tnum">
                    {cube.composite.channels
                      .map(
                        (channel) =>
                          `${channel.channel} ${channel.wavelength_um.toFixed(2)}µm (${channel.band})`,
                      )
                      .join(' · ')}
                  </figcaption>
                  <figcaption className="composite-note">
                    Three wavelengths as red, green and blue, each stretched on its own. False
                    colour, not a photograph.
                  </figcaption>
                </figure>
              )}

              <div className="palettes" role="group" aria-label="colormap">
                {COLORMAPS.map((entry) => (
                  <Swatch
                    key={entry.id}
                    grey={grey}
                    colormap={entry}
                    selected={entry.id === colormap.id}
                    onPick={() => onColormap(entry)}
                  />
                ))}
                <button
                  type="button"
                  className="swatch swatch--random"
                  onClick={() => onColormap(randomColormap())}
                  title="Random palette"
                >
                  <span className="swatch-canvas swatch-random-mark">?</span>
                  <span className="swatch-name mono">Random</span>
                </button>
              </div>
            </div>
          </div>

          <SpectrumChart
            planes={available}
            points={cube.spectrum?.points ?? []}
            active={selected?.index ?? 0}
            onSelect={onPlane}
          />

          <div className="cube-note">
            {cube.notes?.quality ??
              'Visualization grade: the planes and composite are for looking at, not for measuring.'}
            {cube.notes?.position ? ` ${cube.notes.position}` : ''}
          </div>
        </>
      )}

      {available.length === 0 && cube.state !== 'failed' && (
        <div className="build-strip">
          <div className="build-line">
            <span className="build-title">Waiting for the first plane…</span>
          </div>
        </div>
      )}
    </div>
  )
}
