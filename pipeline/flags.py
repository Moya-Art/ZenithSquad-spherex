"""Per-bit quality flags.

`flags != 0` is meaningless: most pixels carry SOURCE, and OVERFLOW coincides with SUR_ERROR. A
pixel is bad only when one of the bits we care about is set, and the bit numbers come from the
`MSKN<bit>` cards in the FLAGS header — not from a hardcoded table.

SATELLITE_HALO is in the list but absent from the 2026 headers; a name the header does not define
is skipped rather than given an invented bit.
"""

from __future__ import annotations

import numpy as np
from astropy.io import fits

BAD_FLAG_NAMES: tuple[str, ...] = (
    "TRANSIENT",
    "OVERFLOW",
    "SUR_ERROR",
    "NONFUNC",
    "DICHROIC",
    "MISSING_DATA",
    "HOT",
    "COLD",
    "NONLINEAR",
    "CROSSTALK",
    "GHOST",
    "GHOST_FPA",
    "GHOST_EXT",
    "STREAK",
    "PERSIST",
    "BLOOM",
    "SNOWBALL",
    "HALO",
    "SATELLITE_HALO",
)

SATURATION_FLAG_NAMES: tuple[str, ...] = ("OVERFLOW", "BLOOM")


def flag_bits(header: fits.Header) -> dict[str, int]:
    """Map every bit name the header defines to its bit number."""
    return {
        str(header[key]).strip(): int(key[4:])
        for key in header
        if key.startswith("MSKN") and key[4:].isdigit()
    }


def resolve_bits(bits: dict[str, int], names: tuple[str, ...] | list[str]) -> list[int]:
    return [bits[name] for name in names if name in bits]


def bad_mask(flags: np.ndarray, bad_bits: list[int]) -> np.ndarray:
    mask = np.zeros(flags.shape, dtype=bool)
    for bit in bad_bits:
        mask |= (flags & (1 << bit)) != 0
    return mask


def has_bit(flags: np.ndarray, selected: list[int]) -> np.ndarray:
    mask = np.zeros(flags.shape, dtype=bool)
    for bit in selected:
        mask |= (flags & (1 << bit)) != 0
    return mask


def bad_fraction(mask: np.ndarray, finite: np.ndarray | None = None) -> float:
    if finite is None:
        return float(mask.mean()) if mask.size else 0.0
    if not finite.any():
        return 0.0
    return float(mask[finite].mean())
