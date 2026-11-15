/**
 * One sentence per target, in plain language, for a visitor who has never opened
 * a FITS file. Phase 4 requires this next to the image.
 *
 * These strings live here rather than in `data/targets.json` because that file is
 * owned by the pipeline phase. When Phase 5 lands they should move there; the keys
 * are the target slugs, so the move is mechanical.
 *
 * Every caption ends on what the tool actually measured, never on a claim.
 */

export const CAPTIONS: Record<string, string> = {
  r_dra:
    'A dying star that swells and shrinks on a roughly 8-month cycle, brightening and fading by hundreds of times.',
  barnard:
    "The fastest-moving star in the sky: it crosses the width of a full Moon in about 180 years.",
  eps_ind:
    'A brown dwarf orbiting the nearby star Epsilon Indi, sharing its rapid drift across the sky.',
  rw_aur:
    'A young star still wrapped in its planet-forming disk, flaring erratically as material falls onto it.',
  wise0855:
    'The coldest known brown dwarf, only about 7 light-years away. So faint that SPHEREx cannot see it in a single frame.',
}

export function captionFor(slug: string): string {
  return CAPTIONS[slug] ?? ''
}
