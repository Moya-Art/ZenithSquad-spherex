"""Flag masking: the bits come from the header, and SOURCE is never bad."""

import numpy as np
from astropy.io import fits

from pipeline.flags import (
    BAD_FLAG_NAMES,
    bad_fraction,
    bad_mask,
    flag_bits,
    has_bit,
    resolve_bits,
)

# The bits ship in the FLAGS header as MSKN<bit>; these are the ones the 2026 files define.
SHIPPED = {
    "TRANSIENT": 0,
    "OVERFLOW": 1,
    "SUR_ERROR": 2,
    "NONFUNC": 6,
    "DICHROIC": 7,
    "MISSING_DATA": 9,
    "HOT": 10,
    "COLD": 11,
    "FULLSAMPLE": 12,
    "PHANMISS": 14,
    "NONLINEAR": 15,
    "PERSIST": 17,
    "OUTLIER": 19,
    "CROSSTALK": 20,
    "SOURCE": 21,
    "GHOST": 22,
    "GHOST_FPA": 23,
    "GHOST_EXT": 24,
    "STREAK": 25,
    "BLOOM": 26,
    "SNOWBALL": 27,
    "HALO": 28,
}


def make_header(mapping=SHIPPED):
    header = fits.Header()
    for name, bit in mapping.items():
        header[f"MSKN{bit:04d}"] = name
        header[f"MSKD{bit:04d}"] = f"{name} description"
    return header


def test_flag_bits_reads_the_mskn_cards():
    bits = flag_bits(make_header())

    assert bits["OVERFLOW"] == 1
    assert bits["SOURCE"] == 21
    assert len(bits) == len(SHIPPED)


def test_a_source_only_pixel_is_not_bad():
    bits = flag_bits(make_header())
    bad = resolve_bits(bits, BAD_FLAG_NAMES)
    flags = np.array([[1 << 21]])

    assert bad_mask(flags, bad).sum() == 0


def test_an_overflow_pixel_is_bad():
    bits = flag_bits(make_header())
    bad = resolve_bits(bits, BAD_FLAG_NAMES)
    flags = np.array([[1 << 1]])

    assert bad_mask(flags, bad).sum() == 1


def test_a_flag_name_the_header_does_not_define_is_skipped():
    bits = flag_bits(make_header({"OVERFLOW": 1}))
    bad = resolve_bits(bits, ("OVERFLOW", "SATELLITE_HALO"))

    assert 1 in bad
    assert len(bad) == 1


def test_bad_fraction_is_taken_over_finite_pixels_only():
    mask = np.array([[True, True], [False, False]])
    finite = np.array([[True, False], [True, True]])

    assert bad_fraction(mask, finite) == 1 / 3
    assert bad_fraction(mask) == 0.5


def test_has_bit_is_per_bit_not_equality():
    flags = np.array([[1 << 21 | 1 << 26]])

    assert has_bit(flags, [26]).all()
    assert not has_bit(flags, [1]).any()
