import { SpectrumChart } from './SpectrumChart'
import { Timeline } from './Timeline'
import type { Cube, Sequence } from './data'

/**
 * The bottom: a video-editor-looking pair of tracks that is read-only.
 *
 * Split left/right to sit under the two plates: dates under the date plate, wavelength under the
 * wavelength plate. Two rulers, not one — time and wavelength are different axes, and sharing a
 * scale would look tidier and be a lie. The resemblance to an editor is a reading aid: there is no
 * trimming, no dragging and no timeline edit here.
 *
 * The band selector lives with the date track, beside the epoch readout, because both describe the
 * date plate.
 */

const BANDS = ['D1', 'D2', 'D3', 'D4', 'D5', 'D6']

type Props = {
  band: string
  onBand: (band: string) => void
  resolvedBand: string | null
  loading: boolean
  sequence: Sequence | null
  index: number
  onSelect: (index: number) => void
  cube: Cube | null
  plane: number
  onPlane: (index: number) => void
}

export function TrackStack({
  band,
  onBand,
  resolvedBand,
  loading,
  sequence,
  index,
  onSelect,
  cube,
  plane,
  onPlane,
}: Props) {
  const activeBand = band || resolvedBand
  const frame = sequence?.frames[index] ?? null

  return (
    <section className="tracks" aria-label="tracks">
      <div className="track-head">
        <div className="track-bands" role="group" aria-label="infrared band">
          {BANDS.map((name) => (
            <button
              key={name}
              type="button"
              className={`band ${name === activeBand ? 'is-active' : ''}`}
              onClick={() => onBand(name)}
              aria-pressed={name === activeBand}
            >
              {name}
            </button>
          ))}
        </div>

        <span className="track-epoch mono tnum">
          {loading ? `loading ${band || '…'} · ` : ''}
          {frame
            ? `epoch ${String(index + 1).padStart(2, '0')}/${String(
                sequence?.frames.length ?? 0,
              ).padStart(2, '0')} · ${frame.date}`
            : 'no epoch yet'}
        </span>
      </div>

      <div className="track-body">
        <div className="track-col track-col--date">
          {sequence && sequence.frames.length > 0 ? (
            <Timeline
              frames={sequence.frames}
              index={index}
              onSelect={onSelect}
              accent="var(--accent)"
            />
          ) : (
            <div className="track-empty">The date track loads with the date plate.</div>
          )}
        </div>

        <div className="track-col track-col--wavelength">
          {cube && cube.planes.length > 0 ? (
            <SpectrumChart
              planes={cube.planes}
              points={cube.spectrum?.points ?? []}
              active={plane}
              onSelect={onPlane}
            />
          ) : (
            <div className="track-empty">
              The wavelength track loads with the wavelength plate.
            </div>
          )}
        </div>
      </div>
    </section>
  )
}
