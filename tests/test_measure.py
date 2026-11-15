"""Photometry and astrometry on a synthetic star: does it recover what we put in?

The PSF here is a Gaussian with sigma 1.2 px, close to the real thing (7.5 arcsec FWHM against a
6.15 arcsec pixel), so a broken centroid or background estimate shows up as a test failure rather
than as a wrong number in the manifest.
"""

from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits
from astropy.wcs import WCS

from pipeline.fits_io import Cutout, pixel_area_sr
from pipeline.measure import measure_frame, sky_offset

SHAPE = (64, 64)
TRUE_X, TRUE_Y = 30.4, 28.7
SIGMA = 1.2
AMPLITUDE = 100.0
BACKGROUND = 5.0
VARIANCE = 0.01


def make_wcs(pixel_scale_arcsec=6.15):
    wcs = WCS(naxis=2)
    wcs.wcs.crpix = [SHAPE[1] / 2, SHAPE[0] / 2]
    wcs.wcs.crval = [248.0, 66.0]
    wcs.wcs.cdelt = [-pixel_scale_arcsec / 3600.0, pixel_scale_arcsec / 3600.0]
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    return wcs


def model(x=TRUE_X, y=TRUE_Y, amplitude=AMPLITUDE):
    yy, xx = np.mgrid[0:SHAPE[0], 0:SHAPE[1]]
    return BACKGROUND + amplitude * np.exp(
        -((xx - x) ** 2 + (yy - y) ** 2) / (2 * SIGMA ** 2)
    )


def make_cutout(image=None, flags=None):
    image = model() if image is None else image
    shape = image.shape
    return Cutout(
        image=image,
        raw=image,
        flags=np.zeros(shape, dtype=np.int64) if flags is None else flags,
        variance=np.full(shape, VARIANCE),
        header=fits.Header(),
        flag_header=fits.Header(),
        wcs=make_wcs(),
        path=Path("synthetic.fits"),
        target_xy=(TRUE_X, TRUE_Y),
        wavelength_um=0.92,
    )


def test_centroid_recovers_a_subpixel_position():
    from pipeline.measure import centroid

    x, y = centroid(model(), (TRUE_X + 1.5, TRUE_Y - 1.2))

    assert x == pytest.approx(TRUE_X, abs=0.2)
    assert y == pytest.approx(TRUE_Y, abs=0.2)


def test_flux_matches_the_sum_inside_the_aperture():
    cutout = make_cutout()
    measurement = measure_frame(cutout, (TRUE_X, TRUE_Y), bad_bits=[], saturation_bits=[8])

    yy, xx = np.mgrid[0:SHAPE[0], 0:SHAPE[1]]
    inside = np.hypot(xx - TRUE_X, yy - TRUE_Y) <= 3.0
    expected = float(np.sum((model() - BACKGROUND)[inside])) * pixel_area_sr(cutout.wcs) * 1e3

    assert measurement.flux == pytest.approx(expected, rel=0.05)
    assert measurement.flux_err > 0
    assert measurement.snr > 0


def test_a_saturated_core_reports_no_snr_and_a_lower_bound():
    flags = np.zeros(SHAPE, dtype=np.int64)
    flags[int(round(TRUE_Y)), int(round(TRUE_X))] = 1 << 8  # OVERFLOW on the core pixel

    measurement = measure_frame(
        make_cutout(flags=flags),
        (TRUE_X, TRUE_Y),
        bad_bits=[8],
        saturation_bits=[8],
    )

    assert measurement.saturated is True
    assert measurement.snr is None
    assert measurement.aperture_flagged >= 1
    assert 0.0 < measurement.bad_fraction < 1.0


def test_bad_fraction_is_believable_not_one_everywhere():
    flags = np.zeros(SHAPE, dtype=np.int64)
    flags[:4, :] = 1 << 0  # a few TRANSIENT rows

    measurement = measure_frame(
        make_cutout(flags=flags), (TRUE_X, TRUE_Y), bad_bits=[0], saturation_bits=[]
    )

    assert 0.0 < measurement.bad_fraction < 0.2


def test_a_wandering_centroid_falls_back_to_the_predicted_position():
    image = model()
    image[int(TRUE_Y) + 3, int(TRUE_X) + 3] += 1e6  # something bright inside the 9x9 box

    measurement = measure_frame(
        make_cutout(image=image), (TRUE_X, TRUE_Y), bad_bits=[], saturation_bits=[]
    )

    assert measurement.centroid_fallback is True
    assert measurement.x == pytest.approx(TRUE_X)
    assert measurement.y == pytest.approx(TRUE_Y)


def test_sky_offset_turns_a_pixel_shift_into_arcseconds():
    wcs_a = make_wcs()
    wcs_b = make_wcs()
    dra, ddec = sky_offset(wcs_a, (32.0, 32.0), wcs_b, (32.0 + 2.0, 32.0 + 1.0))

    assert dra == pytest.approx(-2.0 * 6.15, rel=0.02)
    assert ddec == pytest.approx(1.0 * 6.15, rel=0.02)


def test_wavelength_absent_from_a_synthetic_header_is_none_not_zero():
    cutout = Cutout(
        image=model(),
        raw=model(),
        flags=np.zeros(SHAPE, dtype=np.int64),
        variance=np.full(SHAPE, VARIANCE),
        header=fits.Header(),
        flag_header=fits.Header(),
        wcs=make_wcs(),
        path=Path("synthetic.fits"),
        target_xy=(TRUE_X, TRUE_Y),
        wavelength_um=None,
    )

    measurement = measure_frame(cutout, (TRUE_X, TRUE_Y), bad_bits=[], saturation_bits=[])

    assert measurement.wavelength_um is None
