/**
 * The wavelength plate's data.
 *
 * Loading both sources for every coordinate would charge every visit a 306 MiB tile, so the
 * wavelength plate waits for a click unless a committed cube already exists for this target. Once a
 * build is queued it keeps running on the server; the poll here only reports it.
 */

import { useCallback, useEffect, useState } from 'react'

import { loadCommittedCube, loadCube, type Cube } from './data'

const POLL_MS = 2000

export type CubeLoad = {
  cube: Cube | null
  loading: boolean
  error: string | null
  /** False until the plate has been asked for, or a committed cube answered on its own. */
  requested: boolean
  request: () => void
  retry: () => void
  plane: number
  setPlane: (index: number) => void
}

export function useCube(
  ra: number | null,
  dec: number | null,
  fallbackSlug: string | null,
): CubeLoad {
  const [cube, setCube] = useState<Cube | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [requested, setRequested] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const [plane, setPlane] = useState(0)

  // A committed artifact is free to show; anything else waits for the button.
  useEffect(() => {
    setCube(null)
    setRequested(false)
    setError(null)
    setPlane(0)
    if (!fallbackSlug) return

    let cancelled = false
    loadCommittedCube(fallbackSlug).then((committed) => {
      if (cancelled || !committed) return
      setCube(committed)
      setRequested(true)
    })
    return () => {
      cancelled = true
    }
  }, [fallbackSlug, ra, dec])

  useEffect(() => {
    if (!requested || ra == null || dec == null) return

    let cancelled = false
    let timer: number | undefined
    setError(null)

    const fetchOnce = async () => {
      try {
        const loaded = await loadCube({
          ra,
          dec,
          fallbackSlug,
          refresh: attempt > 0,
        })
        if (cancelled) return
        if (!loaded) {
          setError('The cube request answered with nothing.')
          return
        }
        setCube(loaded)
        if (loaded.state === 'building' || loaded.state === 'queued') {
          timer = window.setTimeout(() => void fetchOnce(), POLL_MS)
        }
      } catch (failure) {
        if (cancelled) return
        setError(failure instanceof Error ? failure.message : String(failure))
      }
    }

    void fetchOnce()
    return () => {
      cancelled = true
      if (timer) window.clearTimeout(timer)
    }
  }, [requested, ra, dec, fallbackSlug, attempt])

  const request = useCallback(() => setRequested(true), [])
  const retry = useCallback(() => {
    setRequested(true)
    setAttempt((current) => current + 1)
  }, [])

  return {
    cube,
    loading: requested && cube === null && error === null,
    error,
    requested,
    request,
    retry,
    plane,
    setPlane,
  }
}
