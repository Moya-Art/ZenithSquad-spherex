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

    let cancelled = false
    setState('loading')
    setSequence(null)
    setError(null)
    setIndex(0)
    setPlaying(false)
    setReady(false)

    loadSequence(ra, dec, {
      band,
      fallback:
        fallbackSlug && fallbackBand ? { slug: fallbackSlug, band: fallbackBand } : null,
    })
      .then((loaded) => {
        if (cancelled) return
        if (!loaded) {
          setState('missing')
          return
        }
        setSequence(loaded)
        setState('idle')
      })
      .catch((failure: Error) => {
        if (cancelled) return
        setState('error')
        setError(failure.message)
      })

    return () => {
      cancelled = true
    }
  }, [ra, dec, band, fallbackSlug, fallbackBand, attempt])

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
