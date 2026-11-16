/**
 * The plate's drawing surface.
 *
 * Every decoded frame is recoloured offscreen, once per palette, before the transport is allowed to
 * advance. Recolouring on each tick would put a flash between frames, and a flash reads as a real
 * change in the sky — the one thing this tool must never invent.
 *
 * `palette === null` means "draw the pixels as they are": that is the RGB composite, which is not
 * greyscale and has no ramp to apply.
 */

import { useEffect, useMemo, useRef } from 'react'

import { applyLut, buildLut, type Colormap } from './colormaps'

type Props = {
  frames: Array<ImageData | null>
  index: number
  palette: Colormap | null
  label: string
}

const recoloured = new WeakMap<ImageData, { paletteId: string; image: ImageData }>()

function recolour(frame: ImageData, palette: Colormap): ImageData {
  // The identity ramp needs no pass: greyscale already *is* what "original" means.
  if (!palette.stops.length) return frame

  // One recoloured copy per frame, for the palette showing now. Caching every palette a visitor
  // tries would hold 102 planes × N palettes of RGBA in memory; regenerating is one pass over
  // 25k pixels, so the previous palette is dropped instead.
  const cached = recoloured.get(frame)
  if (cached?.paletteId === palette.id) return cached.image

  const pixels = new Uint8ClampedArray(frame.data.length)
  pixels.set(frame.data)
  const image = new ImageData(applyLut(pixels, buildLut(palette)), frame.width, frame.height)
  recoloured.set(frame, { paletteId: palette.id, image })
  return image
}

export function PlateCanvas({ frames, index, palette, label }: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)

  const painted = useMemo(
    () => (palette ? frames.map((frame) => (frame ? recolour(frame, palette) : null)) : frames),
    [frames, palette],
  )

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    // Never leave the stage blank: if the wanted frame is not decoded yet, draw the nearest one that
    // is, so an empty rectangle never reads as "the sky is gone".
    let wanted = painted[index] ?? null
    if (!wanted) {
      let bestDistance = Infinity
      painted.forEach((candidate, position) => {
        if (!candidate) return
        const distance = Math.abs(position - index)
        if (distance < bestDistance) {
          bestDistance = distance
          wanted = candidate
        }
      })
    }
    if (!wanted) return

    const context = canvas.getContext('2d')
    if (!context) return
    canvas.width = wanted.width
    canvas.height = wanted.height
    context.imageSmoothingEnabled = false
    context.putImageData(wanted, 0, 0)
  }, [painted, index])

  return (
    <canvas
      ref={canvasRef}
      className="frame-canvas"
      style={{ imageRendering: 'pixelated' }}
      aria-label={label}
    />
  )
}
