"""One stretch per sequence, and a uint8 conversion that cannot manufacture contrast."""

import numpy as np
import pytest

from pipeline.render import global_stretch, to_uint8


def test_the_stretch_is_the_percentile_of_the_concatenation():
    dark = np.full((4, 4), 1.0)
    bright = np.full((4, 4), 2.0)

    vmin, vmax = global_stretch([dark, bright], percentiles=(0.0, 100.0))

    assert vmin == pytest.approx(1.0)
    assert vmax == pytest.approx(2.0)


def test_a_frame_dimmer_than_the_rest_does_not_get_its_own_scale():
    frames = [np.full((4, 4), value) for value in (1.0, 2.0, 3.0)]
    vmin, vmax = global_stretch(frames, percentiles=(0.0, 100.0))

    pixels = [to_uint8(frame, vmin, vmax) for frame in frames]

    assert pixels[0][0, 0] == 0
    assert pixels[2][0, 0] == 255
    assert pixels[1][0, 0] == pytest.approx(128, abs=1)


def test_to_uint8_flips_rows_so_north_is_up_and_clips():
    # row 0 is FITS bottom; after flipud it becomes the last row
    image = np.array([[0.0, 0.5], [1.0, 5.0]])

    pixels = to_uint8(image, 0.0, 1.0)

    assert pixels.dtype == np.uint8
    assert pixels.tolist() == [[255, 255], [0, 128]]


def test_nonfinite_pixels_do_not_become_noise():
    image = np.array([[np.nan, 0.0], [1.0, np.inf]])

    pixels = to_uint8(image, 0.0, 1.0)

    assert pixels[1, 0] == 0    # nan maps to black, not to a random value
    assert pixels[1, 1] == 0    # 0.0
    assert pixels[0, 0] == 255  # 1.0
    assert pixels[0, 1] == 255  # +inf clips to white


def test_an_empty_sequence_is_an_error_not_a_flat_image():
    with pytest.raises(ValueError, match="no finite pixels"):
        global_stretch([np.full((2, 2), np.nan)])
