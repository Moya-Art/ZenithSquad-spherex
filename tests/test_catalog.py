"""Offline tests for the catalogue layer: parsing, counting and epoch grouping.

Nothing here touches the network — every response is canned XML, so a red test means a bug and
never an archive outage.
"""

from datetime import date, timedelta

import pytest

from pipeline.catalog import (
    ArchiveUnknown,
    Frame,
    SchemaError,
    band_label,
    frames_from_rows,
    gaps_days,
    group_epochs,
    mjd_to_date,
    parse_votable,
    summarise,
)

POLYGON = "POLYGON ICRS 259.99143750908775 67.34662051064976,254.503 66.711,248.167 66.754"


def make_votable(field_names, rows, info='<INFO name="QUERY_STATUS" value="OK"/>'):
    fields = "".join(f'<FIELD name="{name}" datatype="char"/>' for name in field_names)
    body = "".join(
        "<TR>" + "".join(f"<TD>{cell}</TD>" for cell in row) + "</TR>" for row in rows
    )
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<VOTABLE version="1.3" xmlns="http://www.ivoa.net/xml/VOTable/v1.3">'
        f'<RESOURCE type="results">{info}'
        f"<TABLE>{fields}<DATA><TABLEDATA>{body}</TABLEDATA></DATA></TABLE>"
        "</RESOURCE></VOTABLE>"
    )


def make_frame(day_offset: int, band: str = "D2", obs_id: str | None = None) -> Frame:
    return Frame(
        obs_id=obs_id or f"obs{day_offset}",
        date=date(2025, 1, 1) + timedelta(days=day_offset),
        mjd=60676 + day_offset,
        band=band,
    )


def test_parse_votable_keeps_a_polygon_that_contains_commas():
    """IRSA's CSV splits this same field on its commas and invents two extra columns."""
    text = make_votable(
        ("obs_id", "t_min", "energy_bandpassname", "s_region"),
        [
            ("2025W20_2D_0243_1", "60785.123", "SPHEREx-D6", POLYGON),
            ("2025W20_2D_0243_1", "60785.130", "SPHEREx-D2", POLYGON),
        ],
    )

    rows = parse_votable(text)

    assert len(rows) == 2
    assert rows[0]["s_region"] == POLYGON
    assert rows[0]["obs_id"] == "2025W20_2D_0243_1"
    assert rows[1]["energy_bandpassname"] == "SPHEREx-D2"


def test_parse_votable_names_the_missing_column():
    text = make_votable(("obs_id", "t_min"), [("2025W20_2D_0243_1", "60785.123")])

    with pytest.raises(SchemaError, match="energy_bandpassname"):
        parse_votable(text)


def test_parse_votable_rejects_a_short_row():
    text = make_votable(("obs_id", "t_min", "energy_bandpassname"), [("2025W20", "60785.123")])

    with pytest.raises(SchemaError, match="row 1"):
        parse_votable(text)


def test_parse_votable_rejects_a_query_error():
    text = make_votable(
        ("obs_id", "t_min", "energy_bandpassname"),
        [],
        info='<INFO name="QUERY_STATUS" value="ERROR"/>',
    )

    with pytest.raises(SchemaError, match="QUERY_STATUS=ERROR"):
        parse_votable(text)


def test_parse_votable_refuses_a_truncated_result():
    text = make_votable(
        ("obs_id", "t_min", "energy_bandpassname"),
        [],
        info='<INFO name="QUERY_STATUS" value="OK"/><INFO name="OVERFLOW" value="10"/>',
    )

    with pytest.raises(ArchiveUnknown, match="truncated"):
        parse_votable(text)


def test_parse_votable_rejects_a_non_xml_body():
    with pytest.raises(SchemaError, match="not VOTable"):
        parse_votable("<html>502 Proxy Error</html")


def test_mjd_to_date():
    assert mjd_to_date(60000) == date(2023, 2, 25)
    assert mjd_to_date(60000.75) == date(2023, 2, 25)


def test_band_label_strips_the_detector_prefix():
    assert band_label("SPHEREx-D6") == "D6"
    assert band_label("spherex-D12") == "D12"
    assert band_label("FUV") == "FUV"


def test_frames_from_rows_rejects_an_unparseable_time():
    rows = [{"obs_id": "x", "t_min": "not-a-number", "energy_bandpassname": "SPHEREx-D2"}]

    with pytest.raises(SchemaError, match="t_min"):
        frames_from_rows(rows)


def test_gaps_days():
    dates = [date(2025, 1, 1), date(2025, 1, 30), date(2025, 3, 1)]

    assert gaps_days(dates) == [29, 30]


def test_group_epochs_keeps_close_dates_together():
    epochs = group_epochs([make_frame(0), make_frame(5), make_frame(29)])

    assert len(epochs) == 1
    assert epochs[0].n_dates == 3
    assert epochs[0].n_frames == 3


def test_group_epochs_splits_on_a_gap_larger_than_the_window():
    epochs = group_epochs([make_frame(0), make_frame(29), make_frame(60)])

    assert [epoch.n_dates for epoch in epochs] == [2, 1]
    assert epochs[1].start == date(2025, 1, 1) + timedelta(days=60)


def test_group_epochs_keeps_dates_exactly_one_window_apart_together():
    assert len(group_epochs([make_frame(0), make_frame(30)])) == 1
    assert len(group_epochs([make_frame(0), make_frame(31)])) == 2


def test_summarise_counts_rows_obs_and_dates_separately():
    frames = [
        make_frame(0, band="D2", obs_id="A"),
        make_frame(0, band="D6", obs_id="A"),
        make_frame(1, band="D2", obs_id="B"),
    ]

    summary = summarise(frames)

    assert summary.n_frames == 3
    assert summary.n_obs == 2
    assert summary.n_dates == 2
    assert summary.first == date(2025, 1, 1)
    assert summary.last == date(2025, 1, 2)
    assert summary.bands == {"D2": {"frames": 2, "dates": 2}, "D6": {"frames": 1, "dates": 1}}


def test_summarise_of_no_rows_is_a_result_not_an_error():
    summary = summarise([])

    assert summary.n_frames == 0
    assert summary.first is None
    assert summary.epochs == []
    assert summary.to_dict()["frames"] == 0


def test_summarise_records_the_radius_that_answered():
    summary = summarise([make_frame(0)], radius_deg=0.01)

    assert summary.radius_deg == 0.01
    assert summary.to_dict()["radius_deg"] == 0.01
    assert "radius_deg" not in summary.counts()
