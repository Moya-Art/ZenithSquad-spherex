import { useEffect, useRef, useState } from 'react'

/**
 * Blink player.
 *
 * Every frame is decoded into an offscreen canvas BEFORE play is enabled. Swapping
 * <img src> flickers, and a flicker reads as a real change in the sky. Drawing from
 * a pre-decoded canvas is a single blit, so nothing between two frames looks different.
 *
 * Frames share one global stretch (vmin/vmax in the manifest), so brightness is
 * comparable across dates without per-frame normalisation.
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
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const bitmaps = useRef<Array<ImageBitmap | null>>([])
  const [ready, setReady] = useState(0)
  const [failed, setFailed] = useState<Set<number>>(new Set())

  // Decode all frames up front. Play stays disabled until everything is in memory.
  useEffect(() => {
    let cancelled = false
    bitmaps.current = sources.map(() => null)
    setReady(0)
    setFailed(new Set())

    Promise.all(
      sources.map(async (src, i) => {
        try {
          const response = await fetch(src)
          if (!response.ok) throw new Error(`HTTP ${response.status}`)
          const bitmap = await createImageBitmap(await response.blob())
          if (cancelled) return
          bitmaps.current[i] = bitmap
          setReady((n) => n + 1)
        } catch {
          if (cancelled) return
          setFailed((prev) => new Set(prev).add(i))
          setReady((n) => n + 1)
        }
      }),
    )

    return () => {
      cancelled = true
      bitmaps.current.forEach((bitmap) => bitmap?.close())
    }
  }, [sources])

  const allLoaded = ready >= sources.length

  // Tell the parent when play becomes legal, so the button can disable itself.
  useEffect(() => {
    onReadyChange?.(allLoaded && sources.length > 0)
  }, [allLoaded, sources.length, onReadyChange])

  // Draw the current frame. Never leave the canvas blank: if the wanted frame has not
  // decoded yet, draw the nearest one that has, so the stage is never an empty rectangle.
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const context = canvas.getContext('2d')
    if (!context) return

    let bitmap = bitmaps.current[index]
    if (!bitmap) {
      let bestDistance = Infinity
      bitmaps.current.forEach((candidate, i) => {
        if (!candidate) return
        const distance = Math.abs(i - index)
        if (distance < bestDistance) {
          bestDistance = distance
          bitmap = candidate
        }
      })
    }
    if (!bitmap) return

    canvas.width = bitmap.width
    canvas.height = bitmap.height
    context.imageSmoothingEnabled = false
    context.drawImage(bitmap, 0, 0)
  }, [index, ready])

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
      <canvas
        ref={canvasRef}
        className="frame-canvas"
        style={{ imageRendering: 'pixelated' }}
        aria-label={labels[index] ?? 'frame'}
      />
      {currentFailed && <div className="frame-badge frame-badge--bad">frame unavailable</div>}
      {loading && (
        <div className="frame-badge">
          loading {ready}/{sources.length}
        </div>
      )}
    </div>
  )
}