/**
 * One decoder for a list of greyscale WebP URLs, shared by both plates.
 *
 * Both sources the server renders are greyscale (Pillow writes mode `L`), so a date frame and a
 * wavelength plane decode the same way. Decoding to `ImageData` once keeps the blink a blit and lets
 * a palette be a table applied to pixels that are already in memory.
 *
 * The cache is module-level and keyed by URL: those responses are `immutable`, so a decoded frame
 * never needs to be fetched twice in a session.
 */

import { useEffect, useState } from 'react'

const CACHE_LIMIT = 256
const CONCURRENCY = 6
const decoded = new Map<string, Promise<ImageData>>()

async function decode(url: string): Promise<ImageData> {
  const response = await fetch(url)
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  const bitmap = await createImageBitmap(await response.blob())
  try {
    const canvas = document.createElement('canvas')
    canvas.width = bitmap.width
    canvas.height = bitmap.height
    const context = canvas.getContext('2d')
    if (!context) throw new Error('no 2d context')
    context.drawImage(bitmap, 0, 0)
    return context.getImageData(0, 0, canvas.width, canvas.height)
  } finally {
    bitmap.close()
  }
}

function decodeCached(url: string): Promise<ImageData> {
  const hit = decoded.get(url)
  if (hit) return hit

  const pending = decode(url)
  decoded.set(url, pending)
  if (decoded.size > CACHE_LIMIT) {
    const oldest = decoded.keys().next().value
    if (oldest !== undefined) decoded.delete(oldest)
  }
  // A failure is not a cache entry: Try again must actually try again.
  pending.catch(() => decoded.delete(url))
  return pending
}

export type GreyFrames = {
  frames: Array<ImageData | null>
  ready: number
  failed: Set<number>
}

export function useGreyFrames(urls: string[]): GreyFrames {
  const [frames, setFrames] = useState<Array<ImageData | null>>(() => urls.map(() => null))
  const [failed, setFailed] = useState<Set<number>>(new Set())
  const [ready, setReady] = useState(0)
  const signature = urls.join('\n')

  useEffect(() => {
    let cancelled = false
    const sources = signature ? signature.split('\n') : []
    const next: Array<ImageData | null> = sources.map(() => null)

    setFrames(next)
    setReady(0)
    setFailed(new Set())

    // 102 planes fetched all at once would be 102 simultaneous requests. A small pool keeps the
    // decoder busy without treating the browser's connection limit as a scheduling policy.
    let cursor = 0
    const worker = async () => {
      while (!cancelled) {
        const index = cursor
        cursor += 1
        if (index >= sources.length) return
        try {
          const image = await decodeCached(sources[index])
          if (cancelled) return
          next[index] = image
          setFrames([...next])
          setReady((count) => count + 1)
        } catch {
          if (cancelled) return
          setFailed((current) => new Set(current).add(index))
          setReady((count) => count + 1)
        }
      }
    }

    for (let i = 0; i < Math.min(CONCURRENCY, sources.length); i += 1) {
      void worker()
    }

    return () => {
      cancelled = true
    }
  }, [signature])

  return { frames, ready, failed }
}
