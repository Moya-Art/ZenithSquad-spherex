/**
 * The wavelength plate: the 102 planes of one patch of sky, plus the RGB composite.
 *
 * The palette list and the spectrum track used to live here. They have moved — the list to the
 * sidebar, the spectrum to the track stack — so this file is only the plate: draw the plane the
 * palette asks for, step through the channels, and say what is still being built.
 */

import { useEffect, useState } from 'react'

import { PlateCanvas } from './PlateCanvas'
import { isComposite, type PaletteEntry } from './colormaps'
import { cubeCompositeUrl, cubePlaneUrl, type Cube } from './data'
import { useGreyFrames } from './useGreyFrames'

type Props = {
  cube: Cube
  plane: number
  onPlane: (index: number) => void
  palette: PaletteEntry
  onRetry: () => void
}

/** Seconds since the build started, updated once a second. */
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

export function ProgressStrip({ cube }: { cube: Cube }) {
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

export function CubeView({ cube, plane, onPlane, palette, onRetry }: Props) {
  const planeUrls = cube.planes.map(cubePlaneUrl)
  const { frames: planeFrames } = useGreyFrames(planeUrls)

  const compositeUrl = cubeCompositeUrl(cube)
  const ramp = isComposite(palette) ? null : palette
  const showComposite = ramp === null
  const { frames: compositeFrames } = useGreyFrames(
    showComposite && compositeUrl ? [compositeUrl] : [],
  )

  const available = cube.planes
  const selected = available.find((entry) => entry.index === plane) ?? available[0] ?? null
  const position = selected ? available.findIndex((entry) => entry.index === selected.index) : -1

  const step = (delta: number) => {
    if (position < 0) return
    const next = available[position + delta]
    if (next) onPlane(next.index)
  }

  return (
    <div className="plate-body">
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
          <div className="frame">
            {showComposite ? (
              <PlateCanvas
                frames={compositeFrames}
                index={0}
                palette={null}
                label={
                  cube.composite
                    ? `${cube.name} in three SPHEREx bands`
                    : 'Three wavelengths as red, green and blue'
                }
              />
            ) : (
              <PlateCanvas
                frames={planeFrames}
                index={position < 0 ? 0 : position}
                palette={ramp}
                label={
                  selected
                    ? `${cube.name} at ${selected.wavelength_um.toFixed(3)} micrometres`
                    : cube.name
                }
              />
            )}

            {showComposite && !compositeFrames[0] && (
              <span className="frame-badge">composite not ready</span>
            )}
            {!showComposite && !planeFrames[position] && (
              <span className="frame-badge">
                loading plane {position + 1}/{available.length}
              </span>
            )}
            {!showComposite && selected?.blank && (
              <span className="frame-badge frame-badge--bad">
                blank by design — dichroic channel
              </span>
            )}
          </div>

          {showComposite && cube.composite ? (
            <div className="plate-caption mono tnum">
              {cube.composite.channels
                .map(
                  (channel) =>
                    `${channel.channel} ${channel.wavelength_um.toFixed(2)}µm (${channel.band})`,
                )
                .join(' · ')}{' '}
              — false colour, not a photograph
            </div>
          ) : (
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
          )}
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
