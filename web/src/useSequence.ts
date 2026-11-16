/**
 * The date plate's data and transport.
 *
 * A sequence is one blocking request that builds every frame against a single stretch. The state is
 * `missing` only when the archive answered "nothing there" — an outage stays an error, because a
 * failed archive and an empty sky are different facts.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'

import {
  frameUrl,
  loadCommittedSequence,
  loadSequence,
  type Frame,
  type Sequence,
  type SequenceFallback,
} from './data'

export type SequenceState = 'idle' | 'loading' | 'missing' | 'error'

export type SequenceLoad = {
  sequence: Sequence | null
  state: SequenceState
  error: string | null
  retry: () => void
  index: number
  setIndex: (index: number) => void
  step: (delta: number) => void
  playing: boolean
  setPlaying: (playing: boolean) => void
  ready: boolean
  setReady: (ready: boolean) => void
  frame: Frame | null
  sources: string[]
  labels: string[]
}

export function useSequence(
  ra: number | null,
  dec: number | null,
  band: string | undefined,
  fallback: SequenceFallback | null,
  settled: boolean,
): SequenceLoad {
  const [sequence, setSequence] = useState<Sequence | null>(null)
  const [state, setState] = useState<SequenceState>('idle')
  const [error, setError] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)
  const [index, setIndex] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [ready, setReady] = useState(false)

  const fallbackSlug = fallback?.slug ?? null
  const fallbackBand = fallback?.band ?? null

  useEffect(() => {
    if (ra == null || dec == null) {
      setSequence(null)
      setState('idle')
      setError(null)
      return
    }

    // Until the target list settles, a coordinate cannot be resolved to a committed artifact, so the
    // request would leave without its fallback. Nothing is in flight yet, so the plate stays idle
    // rather than counting seconds it is not spending.
    if (!settled) return

    const committed: SequenceFallback | null =
      fallbackSlug && fallbackBand ? { slug: fallbackSlug, band: fallbackBand } : null

    let cancelled = false
    setSequence(null)
    setError(null)
    setIndex(0)
    setPlaying(false)
    setReady(false)
    setState(committed ? 'idle' : 'loading')

    void (async () => {
      // The committed copy first. It is a local file, so a named target opens on pixels instead of on
      // a wait; the live request then either replaces it or leaves it standing.
      let instant: Sequence | null = null
      if (committed) {
        instant = await loadCommittedSequence(committed.slug, committed.band)
        if (cancelled) return
        if (instant) {
          setSequence({ ...instant, stale: true })
          setState('idle')
        } else {
          setState('loading')
        }
      }

      try {
        const loaded = await loadSequence(ra, dec, { band, fallback: committed })
        if (cancelled) return
        if (!loaded) {
          // "Nothing there" only reaches the plate when there is no committed copy on screen.
          if (!instant) setState('missing')
          return
        }
        // A live build answers with `source: 'live'`; the committed JSON the loader falls back to does
        // not. Marking that difference is what keeps the caption honest.
        setSequence(loaded.source === 'live' ? loaded : { ...loaded, stale: true })
        setState('idle')
      } catch (failure) {
        if (cancelled) return
        // With the committed copy already on screen a failed request is not an error screen: the data
        // is real, it is just not fresh. The plate says so through `stale`.
        if (instant) return
        setState('error')
        setError((failure as Error).message)
      }
    })()

    return () => {
      cancelled = true
    }
  }, [ra, dec, band, fallbackSlug, fallbackBand, attempt, settled])

  const sources = useMemo(
    () => (sequence ? sequence.frames.map((frame) => frameUrl(frame)) : []),
    [sequence],
  )
  const labels = useMemo(
    () => (sequence ? sequence.frames.map((frame) => frame.date) : []),
    [sequence],
  )

  const step = useCallback(
    (delta: number) => {
      if (!sequence) return
      setPlaying(false)
      setIndex((current) =>
        Math.min(Math.max(current + delta, 0), sequence.frames.length - 1),
      )
    },
    [sequence],
  )

  const retry = useCallback(() => setAttempt((current) => current + 1), [])

  return {
    sequence,
    state,
    error,
    retry,
    index,
    setIndex,
    step,
    playing,
    setPlaying,
    ready,
    setReady,
    frame: sequence?.frames[index] ?? null,
    sources,
    labels,
  }
}
