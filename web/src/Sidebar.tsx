import { Inspector } from './Inspector'
import { PaletteList } from './PaletteList'
import type { PaletteEntry } from './colormaps'
import type { Frame, Sequence } from './data'

/**
 * The right column: what this epoch measured, and how the sky is painted.
 *
 * It scrolls on its own so the plates never have to. The epoch block is the `Inspector` that used to
 * sit beside the image; the colour block is the palette list that used to sit inside the cube view,
 * now shared by both plates.
 */

type Props = {
  sequence: Sequence | null
  frame: Frame | null
  palette: PaletteEntry
  onPalette: (entry: PaletteEntry) => void
  grey: ImageData | null
  compositeUrl: string | null
}

export function Sidebar({ sequence, frame, palette, onPalette, grey, compositeUrl }: Props) {
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
    </aside>
  )
}
