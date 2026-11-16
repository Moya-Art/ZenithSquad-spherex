import { describe, expect, it } from 'vitest'

import type { Target } from './data'
import { resolveTarget, separationDeg, TARGET_TOLERANCE_DEG } from './resolveTarget'

const targets: Target[] = [
  {
    slug: 'r_dra',
    name: 'R Draconis',
    ra: 248.16775,
    dec: 66.75497,
    band: 'D6',
    pm_ra_cosdec: -20.643,
    pm_dec: 6.149,
    pm_source: 'Gaia DR3',
  },
  {
    slug: 'barnard',
    name: "Barnard's Star",
    ra: 269.45402,
    dec: 4.69336,
    band: 'D6',
    pm_ra_cosdec: -801.551,
    pm_dec: 10362.394,
    pm_source: 'Gaia DR3',
  },
  {
    slug: 'wrap_low',
    name: 'Near zero RA',
    ra: 0.00005,
    dec: -10,
    band: 'D6',
    pm_ra_cosdec: 0,
    pm_dec: 0,
    pm_source: 'test',
  },
]

describe('resolveTarget', () => {
  it("recovers Barnard's Star from its coordinates, with its proper motion", () => {
    const found = resolveTarget(269.45402, 4.69336, targets)
    expect(found?.slug).toBe('barnard')
    expect(found?.pm_dec).toBe(10362.394)
  })

  it('does not recover a named target from a near-miss', () => {
    expect(resolveTarget(269.455, 4.69336, targets)).toBeNull()
  })

  it('returns null far from every target', () => {
    expect(resolveTarget(200, -80, targets)).toBeNull()
  })

  it('wraps right ascension across 0/360', () => {
    // 0.00005 and 359.99995 are the same point; the tolerance is 1e-4°, so this must match.
    expect(resolveTarget(359.99998, -10, targets)?.slug).toBe('wrap_low')
  })

  it('uses a tight tolerance', () => {
    expect(TARGET_TOLERANCE_DEG).toBe(1e-4)
    expect(separationDeg(269.45402, 4.69336, targets[1])).toBeCloseTo(0, 9)
  })
})
