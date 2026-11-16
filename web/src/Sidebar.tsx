import { Inspector } from './Inspector'
import { PaletteList } from './PaletteList'
import { isNeutralTint, NEUTRAL_TINT, type Threshold, type Tint } from './colorAdjust'
import type { PaletteEntry } from './colormaps'
import type { Frame, Sequence } from './data'

/**
 * The right column: what this epoch measured, and how the sky is painted.
 *
 * It runs the full height of the workspace and scrolls on its own, so the plates and the tracks never
 * have to. The epoch block is the `Inspector`; below it the palette list and three colour controls:
 * background/highlight, per-channel gains, and a grey-level threshold.
 */

type Props = {
  sequence: Sequence | null
  frame: Frame | null
  palette: PaletteEntry
  onPalette: (entry: PaletteEntry) => void
  grey: ImageData | null
  compositeUrl: string | null
  tint: Tint
  onTint: (tint: Tint) => void
  /** False while the wavelength plate is showing the real-colour composite. */
  tintApplies: boolean
}

const CHANNELS = [
  { key: 'r', label: 'R' },
  { key: 'g', label: 'G' },
  { key: 'b', label: 'B' },
] as const

const MODES = [
  { key: 'above', label: 'Above' },
  { key: 'below', label: 'Below' },
] as const

export function Sidebar({
  sequence,
  frame,
  palette,
  onPalette,
  grey,
  compositeUrl,
  tint,
  onTint,
  tintApplies,
}: Props) {
  const { threshold } = tint

  const setChannel = (key: 'r' | 'g' | 'b', value: number) => {
    onTint({ ...tint, [key]: value })
  }
  const setThreshold = (patch: Partial<Threshold>) => {
    onTint({ ...tint, threshold: { ...threshold, ...patch } })
  }

  return (
    <aside className="sidebar">
      {sequence && frame ? (
        <Inspector sequence={sequence} frame={frame} />
      ) : (
        <div className="sidebar-empty">
          <div className="inspect-key">Epoch</div>
          <p>Signal-to-noise, flux and quality load with the date plate.</p>
        </div>
      )}

      <div className="sidebar-colour">
        <div className="inspect-key">Colour</div>
        <PaletteList
          palette={palette}
          onPalette={onPalette}
          grey={grey}
          compositeUrl={compositeUrl}
        />
      </div>

      <div className="sidebar-tint">
        <div className="inspect-key">Colour adjust</div>

        <label className="tint-color-row">
          <span className="tint-label">Background</span>
          <input
            className="tint-color"
            type="color"
            value={tint.background}
            onChange={(event) => onTint({ ...tint, background: event.target.value })}
            aria-label="Background colour"
          />
          <span className="tint-value mono">{tint.background}</span>
        </label>

        <label className="tint-color-row">
          <span className="tint-label">Highlight</span>
          <input
            className="tint-color"
            type="color"
            value={tint.highlight}
            onChange={(event) => onTint({ ...tint, highlight: event.target.value })}
            aria-label="Highlight colour"
          />
          <span className="tint-value mono">{tint.highlight}</span>
        </label>

        {CHANNELS.map((channel) => (
          <label key={channel.key} className="tint-row">
            <span className="tint-label mono">{channel.label}</span>
            <input
              className="tint-slider"
              type="range"
              min={0}
              max={255}
              value={tint[channel.key]}
              onChange={(event) => setChannel(channel.key, Number(event.target.value))}
              aria-label={`${channel.label} channel gain`}
            />
            <span className="tint-value mono tnum">{tint[channel.key]}</span>
          </label>
        ))}

        <div className="threshold">
          <div className="threshold-head">
            <label className="tint-toggle">
              <input
                type="checkbox"
                checked={threshold.enabled}
                onChange={(event) => setThreshold({ enabled: event.target.checked })}
              />
              <span className="tint-label">Threshold</span>
            </label>

            <div className="threshold-modes" role="group" aria-label="threshold side">
              {MODES.map((mode) => (
                <button
                  key={mode.key}
                  type="button"
                  className={`threshold-mode ${threshold.mode === mode.key ? 'is-active' : ''}`}
                  onClick={() => setThreshold({ mode: mode.key })}
                  aria-pressed={threshold.mode === mode.key}
                >
                  {mode.label}
                </button>
              ))}
            </div>
          </div>

          <label className="tint-row tint-row--wide">
            <span className="tint-label">Level</span>
            <input
              className="tint-slider"
              type="range"
              min={0}
              max={255}
              value={threshold.level}
              onChange={(event) => setThreshold({ level: Number(event.target.value) })}
              aria-label="Threshold grey level"
            />
            <span className="tint-value mono tnum">{threshold.level}</span>
          </label>

          <label className="tint-row tint-row--wide">
            <span className="tint-label">Softness</span>
            <input
              className="tint-slider"
              type="range"
              min={0}
              max={64}
              value={threshold.softness}
              onChange={(event) => setThreshold({ softness: Number(event.target.value) })}
              aria-label="Threshold softness"
            />
            <span className="tint-value mono tnum">{threshold.softness}</span>
          </label>

          <label className="tint-color-row">
            <span className="tint-label">Colour</span>
            <input
              className="tint-color"
              type="color"
              value={threshold.color}
              onChange={(event) => setThreshold({ color: event.target.value })}
              aria-label="Threshold colour"
            />
            <span className="tint-value mono">{threshold.color}</span>
          </label>
        </div>

        <div className="tint-foot">
          <button
            type="button"
            className="tint-reset"
            onClick={() => onTint(NEUTRAL_TINT)}
            disabled={isNeutralTint(tint)}
          >
            Reset
          </button>
          <span className="tint-note">
            {tintApplies
              ? 'Threshold reads the original grey level; gains and the background map apply after the palette.'
              : '3 wavelengths is real colour: these controls paint the date plate only.'}
          </span>
        </div>
      </div>
    </aside>
  )
}
