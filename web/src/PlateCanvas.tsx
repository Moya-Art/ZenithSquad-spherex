/**
 * The plate's drawing surface.
 *
 * Every decoded frame is recoloured offscreen, once per palette and colour adjustment, before the
 * transport is allowed to advance. Recolouring on each tick would put a flash between frames, and a
 * flash reads as a real change in the sky — the one thing this tool must never invent.
 *
 * The optional `tint` is applied after the palette in three steps:
 *   1. per-channel gains (R, G, B), 255 = neutral;
 *   2. a two-point colour map: every pixel is interpolated from `background` (value 0) to
 *      `highlight` (value 255). Black/white is the identity;
 *   3. a threshold read from the ORIGINAL greyscale level: pixels on one side of `level` (with an
 *      optional feathered edge) are painted the chosen colour.
 *
 * `palette === null` means "draw the pixels as they are": that is the RGB composite, which is not
 * greyscale and has no ramp to apply. It is real colour and is never adjusted.
 */

import { useEffect, useMemo, useRef } from 'react'

import { applyLut, buildLut, type Colormap } from './colormaps'
import {
  isNeutralMap,
  isNeutralTint,
  NEUTRAL_TINT,
  parseHex,
  type Threshold,
  type Tint,
} from './colorAdjust'

type Props = {
  frames: Array<ImageData | null>
  index: number
  palette: Colormap | null
  tint?: Tint
  label: string
}

const paintedCache = new WeakMap<ImageData, { key: string; image: ImageData }>()

function applyAdjust(rgba: Uint8ClampedArray, tint: Tint): void {
  const red = tint.r / 255
  const green = tint.g / 255
  const blue = tint.b / 255
  const low = parseHex(tint.background)
  const high = parseHex(tint.highlight)
  const spanR = high[0] - low[0]
  const spanG = high[1] - low[1]
  const spanB = high[2] - low[2]

  for (let i = 0; i < rgba.length; i += 4) {
    const v = Math.min(255, rgba[i] * red) / 255
    const vg = Math.min(255, rgba[i + 1] * green) / 255
    const vb = Math.min(255, rgba[i + 2] * blue) / 255
    rgba[i] = low[0] + spanR * v
    rgba[i + 1] = low[1] + spanG * vg
    rgba[i + 2] = low[2] + spanB * vb
  }
}

/** Paint by greyscale level. `grey` is the frame before any palette, one byte per pixel. */
function applyThreshold(
  rgba: Uint8ClampedArray,
  grey: Uint8ClampedArray,
  threshold: Threshold,
): void {
  const target = parseHex(threshold.color)
  const low = threshold.level - threshold.softness
  const high = threshold.level + threshold.softness
  const span = high - low || 1
  const hard = threshold.softness <= 0

  for (let i = 0; i < rgba.length; i += 4) {
    const level = grey[i]
    let weight: number
    if (hard) {
      const hit = threshold.mode === 'above' ? level >= threshold.level : level <= threshold.level
      weight = hit ? 1 : 0
    } else {
      const t = Math.min(Math.max((level - low) / span, 0), 1)
      weight = threshold.mode === 'above' ? t : 1 - t
    }
    if (weight <= 0) continue

    rgba[i] += (target[0] - rgba[i]) * weight
    rgba[i + 1] += (target[1] - rgba[i + 1]) * weight
    rgba[i + 2] += (target[2] - rgba[i + 2]) * weight
  }
}

function paint(frame: ImageData, palette: Colormap, tint: Tint): ImageData {
  const identityRamp = !palette.stops.length
  if (identityRamp && isNeutralTint(tint)) return frame

  // One painted copy per frame, for the palette and adjustment showing now. Caching every
  // combination a visitor tries would hold 102 planes × N settings of RGBA in memory; regenerating
  // is one pass over 25k pixels, so the previous combination is dropped instead.
  const { threshold } = tint
  const key = [
    palette.id,
    `${tint.r},${tint.g},${tint.b}`,
    tint.background,
    tint.highlight,
    `${threshold.enabled}:${threshold.mode}:${threshold.level}:${threshold.softness}:${threshold.color}`,
  ].join('|')
  const cached = paintedCache.get(frame)
  if (cached?.key === key) return cached.image

  const pixels = new Uint8ClampedArray(frame.data.length)
  pixels.set(frame.data)
  if (!identityRamp) applyLut(pixels, buildLut(palette))
  if (!isNeutralMap(tint)) applyAdjust(pixels, tint)
  if (threshold.enabled) applyThreshold(pixels, frame.data, threshold)

  const image = new ImageData(pixels, frame.width, frame.height)
  paintedCache.set(frame, { key, image })
  return image
}

export function PlateCanvas({ frames, index, palette, tint = NEUTRAL_TINT, label }: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)

  const painted = useMemo(
    () => (palette ? frames.map((frame) => (frame ? paint(frame, palette, tint) : null)) : frames),
    [frames, palette, tint],
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
