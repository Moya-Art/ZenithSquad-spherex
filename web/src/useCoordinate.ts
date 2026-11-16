/**
 * The coordinate is the state.
 *
 * Two fields, two pieces of state, two error messages: a combined string would make `12.5`
 * ambiguous between two different axes. Validation happens per field, before any request, and a
 * submitted value is rounded to five decimals so the link and the request always name the same
 * cache entry.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'

import type { Target } from './data'
import { resolveTarget } from './resolveTarget'
import {
  parseViewState,
  readViewState,
  URL_DECIMALS,
  writeViewState,
  type Position,
} from './viewState'

type FieldErrors = { ra?: string; dec?: string }

type ParsedField = { value: number | null; error: string | null }

function parseField(text: string, axis: 'ra' | 'dec'): ParsedField {
  if (!text.trim()) {
    return { value: null, error: axis === 'ra' ? 'Enter a right ascension' : 'Enter a declination' }
  }
  const parsed = Number(text)
  if (!Number.isFinite(parsed)) return { value: null, error: 'Not a number' }

  const value = Number(parsed.toFixed(URL_DECIMALS))
  if (axis === 'ra') {
    if (value < 0 || value >= 360) return { value: null, error: 'RA must be 0 to 360' }
  } else if (value < -90 || value > 90) {
    return { value: null, error: 'Dec must be −90 to 90' }
  }
  return { value, error: null }
}

function validate(ra: string, dec: string): { position: Position | null; errors: FieldErrors | null } {
  const right = parseField(ra, 'ra')
  const declination = parseField(dec, 'dec')
  const errors: FieldErrors = {}
  if (right.error) errors.ra = right.error
  if (declination.error) errors.dec = declination.error

  if (right.value == null || declination.value == null) {
    return { position: null, errors }
  }
  return { position: { ra: right.value, dec: declination.value }, errors: null }
}

function asInput(value: number): string {
  return value.toFixed(URL_DECIMALS)
}

export type CoordinateState = {
  /** The committed coordinate the loaders use. null when the URL was invalid. */
  position: Position | null
  raInput: string
  decInput: string
  setRaInput: (value: string) => void
  setDecInput: (value: string) => void
  submit: () => void
  /** Jump straight to a coordinate, as a target row does. */
  goTo: (position: Position) => void
  errors: FieldErrors | null
  target: Target | null
  label: string
}

export function useCoordinate(targets: Target[]): CoordinateState {
  const [initialSearch] = useState(() => window.location.search)
  const [initial] = useState(() => parseViewState(initialSearch))

  const raw = useMemo(() => new URLSearchParams(initialSearch), [initialSearch])
  const [position, setPosition] = useState<Position | null>(initial.position)
  const [raInput, setRaInput] = useState(() => raw.get('ra') ?? (initial.position ? asInput(initial.position.ra) : ''))
  const [decInput, setDecInput] = useState(() => raw.get('dec') ?? (initial.position ? asInput(initial.position.dec) : ''))
  const [errors, setErrors] = useState<FieldErrors | null>(() => {
    if (!initial.invalid) return null
    return validate(raw.get('ra') ?? '', raw.get('dec') ?? '').errors
  })

  const apply = useCallback((next: Position) => {
    setPosition(next)
    setRaInput(asInput(next.ra))
    setDecInput(asInput(next.dec))
    setErrors(null)
    writeViewState(next)
  }, [])

  const submit = useCallback(() => {
    const result = validate(raInput, decInput)
    if (!result.position) {
      setErrors(result.errors)
      return
    }
    apply(result.position)
  }, [apply, decInput, raInput])

  const goTo = useCallback(
    (next: Position) => apply(next),
    [apply],
  )

  // Browser back/forward is a coordinate change like any other.
  useEffect(() => {
    const onPop = () => {
      const parsed = readViewState()
      if (parsed.position) {
        setPosition(parsed.position)
        setRaInput(asInput(parsed.position.ra))
        setDecInput(asInput(parsed.position.dec))
        setErrors(null)
      } else {
        setPosition(null)
        const params = new URLSearchParams(window.location.search)
        setRaInput(params.get('ra') ?? '')
        setDecInput(params.get('dec') ?? '')
        setErrors(validate(params.get('ra') ?? '', params.get('dec') ?? '').errors)
      }
    }
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  const target = useMemo(
    () => (position ? resolveTarget(position.ra, position.dec, targets) : null),
    [position, targets],
  )

  const label = useMemo(() => {
    if (target) return target.name
    if (!position) return 'Enter a coordinate'
    const sign = position.dec >= 0 ? '+' : ''
    return `RA ${asInput(position.ra)} · Dec ${sign}${asInput(position.dec)}`
  }, [position, target])

  return {
    position,
    raInput,
    decInput,
    setRaInput,
    setDecInput,
    submit,
    goTo,
    errors,
    target,
    label,
  }
}
