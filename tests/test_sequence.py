"""Band choice and one-frame-per-date selection, on the shapes the real baseline has."""

from datetime import date

import pytest

from pipeline.sequence import FrameRef, one_frame_per_date, pick_band

R_DRA_BANDS = {
    "D1": {"dates": 21, "frames": 67},
    "D2": {"dates": 19, "frames": 70},
    "D3": {"dates": 20, "frames": 71},
    "D4": {"dates": 21, "frames": 65},
    "D5": {"dates": 19, "frames": 70},
    "D6": {"dates": 20, "frames": 70},
}


def ref(obs_id, day, mjd, band="D1", url="https://example/f.fits", available=1):
    return FrameRef(
        obs_id=obs_id,
        date=day,
        mjd=mjd,
        band=band,
        access_url=url,
        frames_available=available,
    )


def test_pick_band_breaks_the_date_tie_on_frames():
    assert pick_band(R_DRA_BANDS) == "D1"


def test_pick_band_takes_more_dates_even_with_fewer_frames():
    bands = {"D2": {"dates": 19, "frames": 70}, "D3": {"dates": 20, "frames": 71}}

    assert pick_band(bands) == "D3"


def test_pick_band_refuses_an_empty_archive():
    with pytest.raises(ValueError, match="no bands"):
        pick_band({})


def test_one_frame_per_date_takes_the_earliest_and_counts_the_rest():
    refs = [
        ref("late", date(2025, 6, 6), 60832.6),
        ref("early", date(2025, 6, 6), 60832.4),
        ref("next", date(2025, 6, 9), 60835.1),
    ]

    chosen = one_frame_per_date(sorted(refs, key=lambda item: (item.date, item.mjd)))

    assert [item.obs_id for item in chosen] == ["early", "next"]
    assert [item.frames_available for item in chosen] == [2, 1]
    assert [item.date for item in chosen] == [date(2025, 6, 6), date(2025, 6, 9)]


def test_one_frame_per_date_keeps_the_order_by_date_not_by_input():
    refs = sorted(
        [ref("b", date(2025, 7, 1), 60857.0), ref("a", date(2025, 6, 1), 60827.0)],
        key=lambda item: (item.date, item.mjd),
    )

    assert [item.date for item in one_frame_per_date(refs)] == [
        date(2025, 6, 1),
        date(2025, 7, 1),
    ]
