"""Cube arithmetic that can be wrong without any network: crops, blank planes, stretch, composite
channel order, and above all the mJy conversion.

Nothing here touches IRSA. The tile-reading path is exercised by `scripts/probe_cube.py` and by the
committed artifact test; these are the pure functions that decide what a plane means.
"""

import numpy as np
import pytest
from astropy import units as u
from astropy.wcs import WCS

from pipeline.cube import (
    ANNULUS_PX,
    APERTURE_PX,
    Plane,
    TileWindow,
    composite_indices,
    coverage,
    crop_window,
    fill_nan,
    local_pixel_scale,
    spectrum_gear,
    spectrum_point,
    tile_for,
    to_uint8_asinh,
)

PIXEL_SCALE = 12.883
WAVELENGTHS = 0.753 + np.arange(102) * (4.988 - 0.753) / 101


def make_wcs(size: int = 64, pixel_scale: float = PIXEL_SCALE) -> WCS:
    wcs = WCS(naxis=2)
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    wcs.wcs.crpix = [size / 2, size / 2]
    wcs.wcs.crval = [248.16775, 66.75497]
    wcs.wcs.cdelt = [-pixel_scale / 3600.0, pixel_scale / 3600.0]
    return wcs


def make_window(
    size: int = 160, peak: float = 10.0, disc_radius: float | None = None,
    blank_everything: bool = False,
) -> TileWindow:
    # 160 px, not 64: the background annulus runs 40-60 px from the target, and a smaller window
    # would put the annulus outside the crop where ApertureStats has nothing to measure.
    wcs = make_wcs(size=size)
    yy, xx = np.mgrid[0:size, 0:size]
    centre = size / 2
    cube = np.zeros((102, size, size))
    for index in range(102):
        level = peak * (1.0 + index / 100.0)
        if disc_radius is None:
            cube[index] = level
        else:
            cube[index] = np.where(
                (xx - centre) ** 2 + (yy - centre) ** 2 <= disc_radius**2, level, 0.0
            )
    hits = np.ones((102, size, size), dtype=np.int32)
    hits[50] = 0
    hits[51] = 0
    if blank_everything:
        hits[:] = 0
    planes = tuple(
        Plane(index=index, detector=index // 17 + 1, subchan=index % 17 + 1,
              wavelength_um=float(WAVELENGTHS[index]), bandwidth_um=0.02)
        for index in range(102)
    )
    return TileWindow(
        cube=cube,
        hits=hits,
        nan_pixels=np.zeros(102, dtype=int),
        planes=planes,
        target_xy=(centre, centre),
        crop_xy=(centre, centre),
        crop=(0, size, 0, size),
        tile_shape=(512, 512),
        pixel_scale_arcsec=PIXEL_SCALE,
        wcs=wcs,
        version="hips_test",
        ipix=2928,
        dirid=0,
        norder=5,
        remote_bytes=320909760,
        mosaic_epoch=2025.84,
    )


def test_tile_url_uses_the_documented_directory_arithmetic():
    tile = tile_for(248.16775, 66.75497, "hips_20261026")

    assert tile.dirid == (tile.ipix // 10000) * 10000
    assert f"Norder{tile.norder}" in tile.url
    assert f"Dir{tile.dirid}/Npix{tile.ipix}_cube.fits" in tile.url
    assert tile.nside == 32


def test_tile_for_is_deterministic_and_follows_the_position():
    first = tile_for(248.16775, 66.75497, "hips_20261026")
    again = tile_for(248.16775, 66.75497, "hips_20261026")
    far = tile_for(10.0, -40.0, "hips_20261026")

    assert first == again
    assert far.ipix != first.ipix


def test_crop_is_clamped_inside_the_tile_at_an_edge():
    # The R Draconis tile puts the target 19.6 px from the left edge; a centred 160 px window would
    # start at x = -60, so it has to stop at the edge instead.
    y0, y1, x0, x1 = crop_window((512, 512), 19.6, 424.8, 0.3, PIXEL_SCALE)

    assert (x0, x1) == (0, 160)
    assert 0 <= y0 < y1 <= 512
    assert y1 - y0 == 160


def test_crop_is_centred_when_there_is_room():
    y0, y1, x0, x1 = crop_window((512, 512), 256.0, 256.0, 0.3, PIXEL_SCALE)

    assert x1 - x0 == 160
    assert abs((x0 + x1) / 2 - 256) <= 1
    assert abs((y0 + y1) / 2 - 256) <= 1


def test_crop_never_exceeds_the_tile():
    y0, y1, x0, x1 = crop_window((512, 512), 500.0, 5.0, 5.0, PIXEL_SCALE)

    assert x1 - x0 <= 512
    assert y1 - y0 <= 512
    assert x1 == 512
    assert y0 == 0


def test_asinh_stretch_is_monotonic_bounded_and_finite():
    plane = np.array([[-1.0, 0.0], [1.0, np.nan]])
    out = to_uint8_asinh(plane, 0.0, 1.0)

    assert out.dtype == np.uint8
    assert out.min() >= 0 and out.max() <= 255
    # FITS row 0 is the bottom, so the array is flipped: 1.0 (white) ends up in the first row.
    assert out[0, 0] == 255
    assert out[0, 1] == 0
    assert out[1, 1] == 0  # NaN is drawn as the floor, never as a bright pixel
    assert out[0, 0] > out[0, 1]


def test_asinh_reaches_the_top_of_the_range_at_vmax():
    assert to_uint8_asinh(np.array([[1.0]]), 0.0, 1.0)[0, 0] == 255
    assert to_uint8_asinh(np.array([[10.0]]), 0.0, 1.0)[0, 0] == 255


def test_fill_nan_replaces_cores_with_a_neighbouring_ceiling():
    plane = np.ones((7, 7)) * 0.5
    plane[3, 3] = np.nan

    filled, count = fill_nan(plane)

    assert count == 1
    assert np.isfinite(filled).all()
    assert filled[3, 3] == pytest.approx(0.5)


def test_coverage_distinguishes_blank_planes_from_covered_ones():
    window = make_window()

    assert coverage(window.hits[0]) == 1.0
    assert coverage(window.hits[50]) == 0.0


def test_composite_picks_three_distinct_planes_red_longest():
    window = make_window()

    indices = composite_indices(window)

    assert len(indices) == 3
    assert len(set(indices)) == 3
    assert 50 not in indices and 51 not in indices
    wavelengths = [window.planes[index].wavelength_um for index in indices]
    # Returned R, G, B order: the red channel is always the longest wavelength.
    assert wavelengths[0] > wavelengths[1] > wavelengths[2]
    for anchor, predicted in zip((4.7, 2.3, 0.9), wavelengths):
        assert abs(predicted - anchor) < 0.35


def test_composite_refuses_a_tile_without_three_covered_planes():
    with pytest.raises(ValueError):
        composite_indices(make_window(blank_everything=True))


def test_spectrum_flux_uses_the_mjy_conversion_not_kjy():
    """The unit that cost this phase a bug: MJy is 1e9 mJy, so a hard-coded 1e3 reports kJy.

    The plane is flat inside the aperture and zero outside, so the expected flux is arithmetic:
    level x aperture area x pixel solid angle, converted to mJy.
    """
    window = make_window(peak=4.0, disc_radius=3.0)
    gear = spectrum_gear(window)
    point = spectrum_point(0, window.cube[0], window.hits[0], gear)

    pixel_scale = local_pixel_scale(window.wcs, *window.target_xy)
    pixel_sr = ((pixel_scale * u.pixel) ** 2).to_value(u.sr)
    filled = float((window.cube[0] > 0).sum())
    expected = 4.0 * filled * pixel_sr * 1e9

    assert point["flux_mjy"] == pytest.approx(expected, rel=1e-3)
    # The discriminating check: a kJy/mJy mix-up would have produced this number divided by 1e6.
    assert point["flux_mjy"] != pytest.approx(expected / 1e6, rel=1e-3)
    # And a sanity anchor on the scale: 4 MJy/sr over ~28 px at 12.9 arcsec/px is a few hundred mJy.
    assert 100.0 < point["flux_mjy"] < 2000.0


def test_spectrum_returns_nothing_for_a_blank_plane():
    window = make_window()
    gear = spectrum_gear(window)

    assert spectrum_point(50, window.cube[50], window.hits[50], gear)["flux_mjy"] is None


def test_spectrum_noise_is_positive_and_scaled_to_mjy():
    window = make_window(peak=4.0, disc_radius=3.0)
    # Gaussian sky noise so the sigma-clipped annulus scatter is a real number rather than zero.
    rng = np.random.default_rng(0)
    window.cube[0] += rng.normal(0.0, 0.02, window.cube[0].shape)
    gear = spectrum_gear(window)
    point = spectrum_point(0, window.cube[0], window.hits[0], gear)

    assert point["noise_mjy"] is not None
    assert point["noise_mjy"] > 0


def test_aperture_and_annulus_are_the_notebooks_pixel_radii():
    window = make_window()
    gear = spectrum_gear(window)

    assert gear["aperture"].r == APERTURE_PX
    assert (gear["annulus"].r_in, gear["annulus"].r_out) == ANNULUS_PX
