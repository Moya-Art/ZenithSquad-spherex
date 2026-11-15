"""Gates on the committed cube artifact, in the same spirit as `test_sequence_artifact.py`.

Skips when the artifact is absent, so a fresh clone without the build is not a failure. Everything it
asserts is something the UI would silently misrender: a missing plane, a shot stretch, a composite
whose bands do not mean anything, or a blank plane that was quietly dropped and shifted the labels.
"""

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CUBE = ROOT / "data" / "fallback" / "cube" / "r_dra.json"


@pytest.fixture(scope="module")
def manifest():
    if not CUBE.exists():
        pytest.skip("the r_dra cube has not been built")
    return json.loads(CUBE.read_text())


def test_the_cube_has_all_102_planes(manifest):
    assert manifest["depth"] == 102
    assert len(manifest["planes"]) == 102
    assert [plane["index"] for plane in manifest["planes"]] == list(range(102))


def test_every_plane_file_exists_and_matches_its_recorded_size(manifest):
    for plane in manifest["planes"]:
        path = CUBE.parent / plane["file"]
        assert path.exists(), plane["file"]
        assert path.stat().st_size == plane["bytes"]
        assert plane["bytes"] <= 60_000


def test_wavelengths_ascend_and_match_the_spectral_table(manifest):
    wavelengths = [plane["wavelength_um"] for plane in manifest["planes"]]
    assert wavelengths == sorted(wavelengths)
    assert 0.75 < wavelengths[0] < 0.76
    assert 4.98 < wavelengths[-1] < 4.99
    bands = [plane["band"] for plane in manifest["planes"]]
    assert bands[0] == "D1" and bands[-1] == "D6"


def test_one_stretch_is_shared_by_every_plane(manifest):
    stretch = manifest["stretch"]
    assert stretch["mode"] == "asinh"
    assert stretch["vmax"] > stretch["vmin"]
    # Nothing per-plane: one scale for the whole cube is the rule §4 implies for wavelengths.
    for plane in manifest["planes"]:
        assert "vmin" not in plane and "vmax" not in plane


def test_the_two_dichroic_planes_are_flagged_rather_than_dropped(manifest):
    assert manifest["blank_planes"] == [50, 51]
    blank = [plane["index"] for plane in manifest["planes"] if plane["blank"]]
    assert blank == [50, 51]
    for plane in manifest["planes"]:
        if plane["blank"]:
            assert plane["coverage"] == 0.0


def test_the_composite_names_three_distinct_bands_red_longest(manifest):
    channels = manifest["composite"]["channels"]
    assert [channel["channel"] for channel in channels] == ["R", "G", "B"]
    wavelengths = [channel["wavelength_um"] for channel in channels]
    assert len(set(wavelengths)) == 3
    assert wavelengths[0] > wavelengths[1] > wavelengths[2]
    for channel in channels:
        assert channel["index"] not in manifest["blank_planes"]
        assert (CUBE.parent / manifest["composite"]["file"]).exists()


def test_the_spectrum_has_one_point_per_plane_and_no_blank_flux(manifest):
    points = manifest["spectrum"]["points"]
    assert [point["index"] for point in points] == list(range(102))
    for point in points:
        if point["index"] in manifest["blank_planes"]:
            assert point["flux_mjy"] is None
        else:
            assert point["flux_mjy"] is not None
            assert point["flux_mjy"] > 0


def test_the_spectrum_is_a_rising_infrared_continuum_for_this_star(manifest):
    """A sanity anchor, not a science claim: R Draconis is a red Mira, so 5 um is far brighter than
    0.75 um, and the peak is at the long-wavelength end."""
    points = {point["index"]: point["flux_mjy"] for point in manifest["spectrum"]["points"]}
    assert points[101] > 5 * points[0]
    assert manifest["spectrum"]["peak_index"] > 95


def test_the_artifact_keeps_its_size_budget(manifest):
    total = sum(plane["bytes"] for plane in manifest["planes"]) + manifest["composite"]["bytes"]
    assert total < 3_000_000


def test_the_manifest_says_it_is_visualization_grade(manifest):
    quality = manifest["notes"]["quality"]
    assert "Visualization grade" in quality
    assert "IRSA SPHEREx Spectrophotometry tool" in quality
