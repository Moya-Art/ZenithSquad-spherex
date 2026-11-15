"""The committed r_dra sequence, checked against the build plan's §7 gates.

This is the only test that reads a real artefact rather than a synthetic one, and it is the reason
the gates are worth writing down: a regression in the stretch, the WebP sizes or the flag mask shows
up here without touching the network.
"""

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SEQUENCE = REPO / "data" / "fallback" / "r_dra" / "sequence.json"


@pytest.fixture(scope="module")
def manifest():
    if not SEQUENCE.exists():
        pytest.skip("r_dra sequence has not been built")
    return json.loads(SEQUENCE.read_text())


def test_every_frame_shares_one_stretch(manifest):
    assert manifest["vmax"] > manifest["vmin"]
    for frame in manifest["frames"]:
        assert "vmin" not in frame and "vmax" not in frame


def test_every_frame_has_a_webp_under_60_kb(manifest):
    for frame in manifest["frames"]:
        path = SEQUENCE.parent / frame["webp"]
        assert path.exists(), frame["webp"]
        assert path.stat().st_size <= 60_000, frame["webp"]
        assert frame["bytes"] == path.stat().st_size


def test_bad_fraction_is_believable_rather_than_one_everywhere(manifest):
    fractions = [frame["bad_fraction"] for frame in manifest["frames"]]
    assert all(0.0 < value < 0.5 for value in fractions)


def test_dates_are_unique_and_in_order(manifest):
    dates = [frame["date"] for frame in manifest["frames"]]
    assert dates == sorted(set(dates))
    assert len(dates) == manifest["n_frames"]


def test_the_manifest_does_not_claim_motion_it_cannot_measure(manifest):
    if manifest["saturated_any"]:
        assert manifest["motion_reliable"] is False
        assert "saturated" in manifest["motion_note"]
