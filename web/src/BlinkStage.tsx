import { useEffect } from 'react'

import { PlateCanvas } from './PlateCanvas'
import type { Colormap } from './colormaps'
import { useGreyFrames } from './useGreyFrames'

/**
 * The date plate's player.
 *
 * Every frame is decoded before play is enabled, and `PlateCanvas` has already recoloured all of them
 * for the current palette, so advancing the transport is a single blit. Swapping a source or
 * recolouring on demand flashes, and a flash reads as a real change in the sky.
 */

type Props = {
  sources: string[]
  labels: string[]
  fps?: number
  index: number
  onIndexChange: (index: number) => void
  playing: boolean
  onPlayingChange: (playing: boolean) => void
  onReadyChange?: (ready: boolean) => void
  palette: Colormap
}

export function BlinkStage({
  sources,
  labels,
  fps = 2,
  index,
  onIndexChange,
  playing,
  onPlayingChange,
  onReadyChange,
  palette,
}: Props) {
  const { frames, ready, failed } = useGreyFrames(sources)
  const allLoaded = sources.length > 0 && ready >= sources.length

  // Tell the parent when play becomes legal, so the button can disable itself.
  useEffect(() => {
    onReadyChange?.(allLoaded)
  }, [allLoaded, onReadyChange])

  // Transport.
  useEffect(() => {
    if (!playing || !allLoaded) return
    const timer = window.setInterval(() => {
      onIndexChange((index + 1) % sources.length)
    }, 1000 / fps)
    return () => window.clearInterval(timer)
  }, [playing, allLoaded, index, sources.length, fps, onIndexChange])

  // Stop at the end rather than looping silently forever.
  useEffect(() => {
    if (playing && index === sources.length - 1) {
      const timer = window.setTimeout(() => onPlayingChange(false), 1000 / fps)
      return () => window.clearTimeout(timer)
    }
  }, [playing, index, sources.length, fps, onPlayingChange])

  const currentFailed = failed.has(index)
  const loading = !allLoaded

  return (
    <div className="frame">
      <PlateCanvas frames={frames} index={index} palette={palette} label={labels[index] ?? 'frame'} />
      {currentFailed && <div className="frame-badge frame-badge--bad">frame unavailable</div>}
      {loading && (
        <div className="frame-badge">
          loading {ready}/{sources.length}
        </div>
      )}
    </div>
  )
}
