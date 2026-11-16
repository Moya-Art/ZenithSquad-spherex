import { useEffect, useRef } from 'react'

import {
  buildLut,
  isComposite,
  PALETTES,
  randomColormap,
  type Colormap,
  type PaletteEntry,
} from './colormaps'

/**
 * One palette for both plates.
 *
 * The list is a table applied to pixels that are already downloaded, so a swatch is a thumbnail of
 * the plate you are looking at, not another image. The composite is the one entry that is not a ramp:
 * it is labelled `3 wavelengths` because it only changes the wavelength plate, and a control that
 * silently did nothing on the other plate would read as a bug.
 */

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

type Props = {
  palette: PaletteEntry
  onPalette: (entry: PaletteEntry) => void
  /** The plane or frame the swatches preview; null before anything is decoded. */
  grey: ImageData | null
  compositeUrl: string | null
}

export function PaletteList({ palette, onPalette, grey, compositeUrl }: Props) {
  return (
    <div className="palettes" role="group" aria-label="colour palette">
      {PALETTES.map((entry) => {
        if (isComposite(entry)) {
          const selected = palette.id === entry.id
          return (
            <button
              key={entry.id}
              type="button"
              className={`swatch ${selected ? 'is-active' : ''}`}
              onClick={() => onPalette(entry)}
              aria-pressed={selected}
              title="Shows three wavelengths in the wavelength plate; the date plate keeps its ramp."
            >
              {compositeUrl ? (
                <img className="swatch-canvas" src={compositeUrl} alt="" />
              ) : (
                <span className="swatch-canvas swatch-composite-mark" aria-hidden="true" />
              )}
              <span className="swatch-name mono">{entry.name}</span>
            </button>
          )
        }
        return (
          <Swatch
            key={entry.id}
            grey={grey}
            colormap={entry}
            selected={palette.id === entry.id}
            onPick={() => onPalette(entry)}
          />
        )
      })}

      <button
        type="button"
        className="swatch swatch--random"
        onClick={() => onPalette(randomColormap())}
        title="Random palette"
      >
        <span className="swatch-canvas swatch-random-mark">?</span>
        <span className="swatch-name mono">Surprise me</span>
      </button>
    </div>
  )
}
