import { describe, expect, it } from 'vitest'

import {
  canonicalViewState,
  DEFAULT_POSITION,
  parseViewState,
  serializeViewState,
  URL_DECIMALS,
} from './viewState'

describe('parseViewState', () => {
  it('falls back to the default position when the URL is empty', () => {
    expect(parseViewState('')).toEqual({ position: DEFAULT_POSITION, invalid: false })
  })

  it('reads a coordinate', () => {
    expect(parseViewState('?ra=269.45402&dec=4.69336')).toEqual({
      position: { ra: 269.45402, dec: 4.69336 },
      invalid: false,
    })
  })

  it('ignores parameters the URL no longer carries', () => {
    const parsed = parseViewState('?target=barnard&ra=1&dec=2&band=D6&mode=cube&plane=3&cmap=hot')
    expect(parsed).toEqual({ position: { ra: 1, dec: 2 }, invalid: false })
  })

  it('rejects an out-of-range coordinate before any request', () => {
    expect(parseViewState('?ra=999&dec=4.69336')).toEqual({ position: null, invalid: true })
    expect(parseViewState('?ra=10&dec=-91')).toEqual({ position: null, invalid: true })
    expect(parseViewState('?ra=-1&dec=0')).toEqual({ position: null, invalid: true })
  })

  it('rejects a value that is not a number', () => {
    expect(parseViewState('?ra=abc&dec=0')).toEqual({ position: null, invalid: true })
    expect(parseViewState('?ra=&dec=0')).toEqual({ position: null, invalid: true })
  })

  it('rejects a half-given coordinate', () => {
    expect(parseViewState('?ra=10')).toEqual({ position: null, invalid: true })
    expect(parseViewState('?dec=10')).toEqual({ position: null, invalid: true })
  })

  it('accepts the edges of both ranges', () => {
    expect(parseViewState('?ra=0&dec=-90')).toEqual({
      position: { ra: 0, dec: -90 },
      invalid: false,
    })
    expect(parseViewState('?ra=359.99999&dec=90')).toEqual({
      position: { ra: 359.99999, dec: 90 },
      invalid: false,
    })
  })
})

describe('canonicalViewState', () => {
  it('fills the bar in when nothing was asked for', () => {
    expect(canonicalViewState('')).toEqual({
      position: DEFAULT_POSITION,
      url: '?ra=248.16775&dec=66.75497',
      repaired: false,
    })
  })

  it('leaves a coordinate the bar already states exactly alone', () => {
    expect(canonicalViewState('?ra=269.45402&dec=4.69336')).toEqual({
      position: { ra: 269.45402, dec: 4.69336 },
      url: null,
      repaired: false,
    })
  })

  it('normalizes precision rather than rewriting a different coordinate', () => {
    expect(canonicalViewState('?ra=269.4540249&dec=4.6933601')).toEqual({
      position: { ra: 269.45402, dec: 4.69336 },
      url: '?ra=269.45402&dec=4.69336',
      repaired: false,
    })
  })

  it('strips a coordinate that was never valid, so a reload cannot inherit it', () => {
    expect(canonicalViewState('?ra=999&dec=4.69336')).toEqual({
      position: null,
      url: '',
      repaired: true,
    })
    expect(canonicalViewState('?ra=10')).toEqual({ position: null, url: '', repaired: true })
  })

  it('drops the parameters the URL no longer carries', () => {
    expect(canonicalViewState('?target=barnard&ra=1&dec=2&mode=cube').url).toBe('?ra=1.00000&dec=2.00000')
  })
})

describe('serializeViewState', () => {
  it('rounds to the cache key precision', () => {
    expect(serializeViewState({ ra: 248.167754, dec: 66.754974 })).toBe(
      '?ra=248.16775&dec=66.75497',
    )
    expect(URL_DECIMALS).toBe(5)
  })

  it('round-trips a parsed coordinate', () => {
    const search = '?ra=269.45402&dec=4.69336'
    const parsed = parseViewState(search)
    expect(parsed.position).not.toBeNull()
    if (!parsed.position) return
    expect(serializeViewState(parsed.position)).toBe(search)
  })

  it('rounds before the request, so link and request agree', () => {
    const parsed = parseViewState('?ra=248.167754123&dec=66.754973999')
    expect(parsed.position).not.toBeNull()
    if (!parsed.position) return
    const rounded = parseViewState(serializeViewState(parsed.position))
    expect(rounded.position).toEqual({
      ra: Number(parsed.position.ra.toFixed(5)),
      dec: Number(parsed.position.dec.toFixed(5)),
    })
  })
})
