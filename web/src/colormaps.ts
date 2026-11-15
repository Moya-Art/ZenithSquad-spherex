/**
 * Colormaps for the 102 wavelength planes.
 *
 * These are anchor sets, not matplotlib's exact 256-entry tables: each is interpolated to 256 stops.
 * That is a deliberate approximation — a display palette needs to look right on a small plane, not to
 * be bit-identical — and it keeps the app's runtime dependencies at react + react-dom.
 *
 * The whole feature is a lookup table applied to the greyscale plane that was already downloaded, so
 * switching palette costs one pass over an ImageData buffer and no network at all.
 */

export type Colormap = {
  id: string
  name: string
  /** Anchor colours, low to high. Empty means the plane's own greyscale. */
  stops: string[]
}

export const COLORMAPS: Colormap[] = [
  { id: 'greyscale', name: 'Greyscale', stops: [] },
  { id: 'inferno', name: 'Inferno', stops: [
    '#000004', '#1b0c41', '#4a0c6b', '#781c6d', '#a52c60',
    '#cf4446', '#ed6925', '#fb9b06', '#f7d13d', '#fcffa4',
  ] },
  { id: 'viridis', name: 'Viridis', stops: [
    '#440154', '#482878', '#3e4989', '#31688e', '#26828e',
    '#1f9e89', '#35b779', '#6ece58', '#b5de2b', '#fde725',
  ] },
  { id: 'magma', name: 'Magma', stops: [
    '#000004', '#180f3d', '#440f76', '#721f81', '#9e2f7f',
    '#cd4071', '#f1605d', '#fd9668', '#feca8d', '#fcfdbf',
  ] },
  { id: 'plasma', name: 'Plasma', stops: [
    '#0d0887', '#46039f', '#7201a8', '#9c179e', '#bd3786',
    '#d8576b', '#ed7953', '#fb9f3a', '#fdca26', '#f0f921',
  ] },
  { id: 'cividis', name: 'Cividis', stops: [
    '#00224e', '#123570', '#3b496c', '#575d6d', '#707173',
    '#8a8678', '#a59c74', '#c3b369', '#e1cc55', '#fee838',
  ] },
  { id: 'turbo', name: 'Turbo', stops: [
    '#30123b', '#4145ab', '#4675ed', '#39a2fc', '#1bcfd4', '#24eca6',
    '#61fc6c', '#a4fc3b', '#d1e834', '#f3c63a', '#fe9b2d', '#f36315',
    '#d93806', '#b11901', '#7a0402',
  ] },
  { id: 'rainbow', name: 'Rainbow', stops: [
    '#00007f', '#0000ff', '#007fff', '#00ffff', '#7fff7f',
    '#ffff00', '#ff7f00', '#ff0000', '#7f0000',
  ] },
  { id: 'blues', name: 'Blues', stops: [
    '#f7fbff', '#deebf7', '#c6dbef', '#9ecae1', '#6baed6',
    '#4292c6', '#2171b5', '#08519c', '#08306b',
  ] },
  { id: 'hot', name: 'Hot', stops: [
    '#0b0000', '#4d0000', '#a30000', '#ff0000', '#ff8c00',
    '#ffd700', '#ffffcc', '#ffffff',
  ] },
  { id: 'cubehelix', name: 'Cubehelix', stops: [
    '#000000', '#1a0a2e', '#3b1250', '#6b1f5f', '#a02f56',
    '#cc5049', '#e88b4a', '#f5c86e', '#f7efc0', '#ffffff',
  ] },
]

function parseHex(hex: string): [number, number, number] {
  const value = Number.parseInt(hex.replace('#', ''), 16)
  return [(value >> 16) & 255, (value >> 8) & 255, value & 255]
}

const lutCache = new Map<string, Uint8Array>()

/** 256 x 3 bytes. An empty stop list is the identity, which is what "original" means. */
export function buildLut(colormap: Colormap): Uint8Array {
  const cacheKey = colormap.stops.length ? colormap.stops.join(',') : 'identity'
  const cached = lutCache.get(cacheKey)
  if (cached) return cached

  const lut = new Uint8Array(256 * 3)
  if (!colormap.stops.length) {
    for (let i = 0; i < 256; i += 1) {
      lut[i * 3] = i
      lut[i * 3 + 1] = i
      lut[i * 3 + 2] = i
    }
  } else {
    const anchors = colormap.stops.map(parseHex)
    for (let i = 0; i < 256; i += 1) {
      const position = (i / 255) * (anchors.length - 1)
      const low = Math.floor(position)
      const high = Math.min(low + 1, anchors.length - 1)
      const fraction = position - low
      for (let channel = 0; channel < 3; channel += 1) {
        lut[i * 3 + channel] = Math.round(
          anchors[low][channel] + (anchors[high][channel] - anchors[low][channel]) * fraction,
        )
      }
    }
  }

  lutCache.set(cacheKey, lut)
  return lut
}

/** Recolour in place: the red channel of a greyscale plane indexes the table. */
export function applyLut(rgba: Uint8ClampedArray, lut: Uint8Array): Uint8ClampedArray {
  for (let i = 0; i < rgba.length; i += 4) {
    const index = rgba[i] * 3
    rgba[i] = lut[index]
    rgba[i + 1] = lut[index + 1]
    rgba[i + 2] = lut[index + 2]
  }
  return rgba
}

function hslToHex(hue: number, saturation: number, lightness: number): string {
  const chroma = (1 - Math.abs(2 * lightness - 1)) * saturation
  const sector = hue / 60
  const second = chroma * (1 - Math.abs((sector % 2) - 1))
  const [r, g, b] =
    sector < 1 ? [chroma, second, 0]
    : sector < 2 ? [second, chroma, 0]
    : sector < 3 ? [0, chroma, second]
    : sector < 4 ? [0, second, chroma]
    : sector < 5 ? [second, 0, chroma]
    : [chroma, 0, second]
  const m = lightness - chroma / 2
  const channel = (value: number) =>
    Math.round(Math.min(Math.max((value + m) * 255, 0), 255))
      .toString(16)
      .padStart(2, '0')
  return `#${channel(r)}${channel(g)}${channel(b)}`
}

/**
 * A ramp that stays readable rather than mud: hue walks a random direction, lightness rises
 * monotonically from near-black to near-white so faint structure never becomes invisible.
 */
export function randomStops(): string[] {
  const count = 5 + Math.floor(Math.random() * 2)
  const start = Math.random() * 360
  const swing = (Math.random() < 0.5 ? -1 : 1) * (90 + Math.random() * 220)
  const saturation = 0.55 + Math.random() * 0.45
  return Array.from({ length: count }, (_, index) => {
    const t = index / (count - 1)
    const hue = (start + swing * t + 360) % 360
    const lightness = 0.06 + 0.9 * t
    return hslToHex(hue, saturation * (0.55 + 0.45 * Math.sin(Math.PI * t)), lightness)
  })
}

export function randomColormap(): Colormap {
  return { id: `random-${Date.now()}`, name: 'Surprise me', stops: randomStops() }
}
