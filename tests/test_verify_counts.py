"""Tests for the baseline diff in scripts/verify_counts.py — no network, no subprocess."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import verify_counts  # noqa: E402

CURRENT = {
    "frames": 261,
    "obs": 131,
    "dates": 28,
    "first": "2025-05-05",
    "last": "2026-05-14",
    "radius_deg": 0.001,
    "bands": {"D2": {"frames": 48, "dates": 14}, "D6": {"frames": 45, "dates": 13}},
}


def test_identical_measurements_do_not_drift():
    assert verify_counts.describe_drift(CURRENT, dict(CURRENT)) == ""


def test_a_missing_baseline_row_is_reported_as_such():
    assert verify_counts.describe_drift(CURRENT, None) == "no baseline row"


def test_count_drift_is_signed():
    drift = verify_counts.describe_drift(CURRENT, {**CURRENT, "frames": 258})

    assert drift == "frames 261/258 (+3)"


def test_band_drift_names_the_band():
    before = {**CURRENT, "bands": {"D2": {"frames": 70, "dates": 19}, "D6": {"frames": 45, "dates": 13}}}

    assert verify_counts.describe_drift(CURRENT, before) == "D2 frames 48/70, D2 dates 14/19"


def test_a_baseline_without_bands_or_radius_does_not_invent_drift():
    legacy = {key: CURRENT[key] for key in ("frames", "obs", "dates", "first", "last")}

    assert verify_counts.describe_drift(CURRENT, legacy) == ""


def test_many_changes_stay_readable():
    before = {
        **CURRENT,
        "frames": 1,
        "obs": 2,
        "dates": 3,
        "first": "2020-01-01",
        "last": "2020-01-02",
        "bands": {"D2": {"frames": 70, "dates": 19}, "D6": {"frames": 40, "dates": 13}},
    }

    drift = verify_counts.describe_drift(CURRENT, before)

    assert drift.count(",") == 6
    assert drift.endswith("(2 more)")
