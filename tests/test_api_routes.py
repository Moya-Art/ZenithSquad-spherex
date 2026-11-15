"""The routes, with `service` patched so nothing here touches IRSA.

What is being tested is not FastAPI: it is that a failure keeps its identity. A measured zero is a
404, an unreachable archive is a 503 that becomes a stale 200 when a cache can answer, and no response
is ever a FITS body.
"""

import pytest
from fastapi.testclient import TestClient

from pipeline import catalog

from api.app import main, service

MANIFEST = {
    "target": "r_dra",
    "name": "R Draconis",
    "band": "D1",
    "size_deg": 0.3,
    "vmin": 0.024,
    "vmax": 3.985,
    "pixscale_arcsec": 6.15,
    "generated_by": "test",
    "note": "test manifest",
    "collection": "spherex_dr1",
    "band_wavelength_um": [0.75, 1.09],
    "built": "2026-11-15",
    "n_frames": 1,
    "n_bands_available": 6,
    "available_bands": {"D1": {"frames": 67, "dates": 21}},
    "saturated_any": True,
    "frames": [
        {
            "date": "2025-06-06",
            "t_min": 60832.4,
            "obs_id": "obs-a",
            "file": "r_dra_D1_2025-06-06.webp",
            "bytes": 500,
            "bad_fraction": 0.02,
            "outlier": {"mean": 0.0, "median": 0.0, "max_abs": 0.0},
            "measure": None,
            "saturated": True,
            "centroid_from_prediction": False,
        }
    ],
    "motion": {
        "dx_arcsec": 0.0,
        "dy_arcsec": 0.0,
        "dt_years": 1.0,
        "slope_arcsec_per_year": [0.0, 0.0],
        "slope_err": [0.1, 0.1],
        "rms_scatter_arcsec": [0.2, 0.2],
        "total_arcsec": 0.0,
        "significant": False,
        "reliable": False,
    },
}

WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 "


@pytest.fixture()
def client():
    return TestClient(main.app)


def test_targets_are_the_five_from_targets_json(client):
    body = client.get("/targets").json()

    slugs = [target["slug"] for target in body["targets"]]
    assert slugs == ["r_dra", "wise0855", "barnard", "eps_ind", "rw_aur"]


def test_frames_reports_a_miss_then_a_hit(client, monkeypatch):
    calls = []

    def fake_live(ra, dec, band=None, **kwargs):
        calls.append((ra, dec, band))
        return dict(MANIFEST), "miss" if len(calls) == 1 else "hit"

    monkeypatch.setattr(service, "live_sequence", fake_live)

    first = client.get("/frames", params={"target": "r_dra", "band": "D1"})
    second = client.get("/frames", params={"target": "r_dra", "band": "D1"})

    assert first.status_code == 200
    assert first.headers["X-Cache"] == "miss"
    assert second.headers["X-Cache"] == "hit"
    assert first.json()["vmax"] == MANIFEST["vmax"]


def test_a_zero_frame_coordinate_is_404_never_an_empty_200(client, monkeypatch):
    def no_coverage(*args, **kwargs):
        raise service.NoCoverage("0 frames in spherex_dr1 at RA 10 Dec 0")

    monkeypatch.setattr(service, "live_sequence", no_coverage)

    response = client.get("/frames", params={"ra": 10, "dec": 0, "band": "D1"})

    assert response.status_code == 404
    assert "0 frames" in response.json()["detail"]


def test_an_unreachable_archive_without_a_cache_is_503(client, monkeypatch):
    def down(*args, **kwargs):
        raise catalog.ArchiveUnknown("HTTP Error 502: Proxy Error")

    monkeypatch.setattr(service, "live_sequence", down)
    monkeypatch.setattr(service, "cached_sequence", lambda *args: None)

    response = client.get("/frames", params={"ra": 10, "dec": 0, "band": "D1"})

    assert response.status_code == 503
    assert "did not answer" in response.json()["detail"]


def test_an_unreachable_archive_with_a_cache_serves_it_as_stale(client, monkeypatch):
    def down(*args, **kwargs):
        raise catalog.ArchiveUnknown("HTTP Error 502: Proxy Error")

    monkeypatch.setattr(service, "live_sequence", down)
    monkeypatch.setattr(
        service, "cached_sequence", lambda *args: {**MANIFEST, "source": "live", "stale": False}
    )

    response = client.get("/frames", params={"ra": 10, "dec": 0, "band": "D1"})

    assert response.status_code == 200
    assert response.json()["stale"] is True
    assert response.headers["Cache-Control"] == "no-store"


def test_a_preview_is_webp_with_an_etag_and_an_immutable_cache(client, monkeypatch):
    monkeypatch.setattr(service, "preview_webp", lambda *args, **kwargs: (WEBP, "miss"))

    response = client.get(
        "/preview",
        params={"obs_id": "obs-a", "ra": 248.16775, "dec": 66.75497, "band": "D1", "size": 0.3},
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/webp"
    assert "fits" not in response.headers["content-type"]
    assert response.headers["X-Cache"] == "miss"
    assert response.headers["ETag"].startswith('"')
    assert "immutable" in response.headers["Cache-Control"]


def test_a_matching_etag_answers_304_without_a_body(client, monkeypatch):
    monkeypatch.setattr(service, "preview_webp", lambda *args, **kwargs: (WEBP, "hit"))
    params = {"obs_id": "obs-a", "ra": 248.16775, "dec": 66.75497, "band": "D1", "size": 0.3}

    first = client.get("/preview", params=params)
    again = client.get(
        "/preview", params=params, headers={"If-None-Match": first.headers["ETag"]}
    )

    assert again.status_code == 304
    assert again.content == b""


def test_an_obs_id_outside_the_sequence_is_404(client, monkeypatch):
    def unknown(*args, **kwargs):
        raise service.UnknownFrame("obs-z is not in the D1 sequence")

    monkeypatch.setattr(service, "preview_webp", unknown)

    response = client.get(
        "/preview",
        params={"obs_id": "obs-z", "ra": 1, "dec": 2, "band": "D1", "size": 0.3},
    )

    assert response.status_code == 404


def test_the_cube_route_asks_for_a_position(client):
    """A cube needs a target slug or both coordinates. Half a coordinate never reaches the pipeline,
    which is why this asserts 422 rather than starting a 306 MiB download inside a test."""
    assert client.get("/cube").status_code == 422
    assert client.get("/cube", params={"ra": 10}).status_code == 422


def test_healthz_names_the_archive_and_the_cache(client):
    body = client.get("/healthz").json()

    for key in (
        "status",
        "last_irsa_contact",
        "cache_writable",
        "targets",
        "collection",
        "version",
        "bucket_reachable",
    ):
        assert key in body


@pytest.mark.parametrize(
    "params",
    [
        {"ra": 999, "dec": 0, "band": "D1"},
        {"ra": 10, "dec": 91, "band": "D1"},
        {"ra": 10, "dec": 0, "band": "D1", "size": 0},
        {"ra": 10, "dec": 0, "band": "X9"},
        {"band": "D1"},
    ],
)
def test_bad_parameters_are_422(client, params):
    assert client.get("/frames", params=params).status_code == 422


def test_no_route_ever_answers_with_fits(client, monkeypatch):
    monkeypatch.setattr(service, "live_sequence", lambda *args, **kwargs: (dict(MANIFEST), "hit"))
    monkeypatch.setattr(service, "preview_webp", lambda *args, **kwargs: (WEBP, "hit"))
    # Patched, not merely called: an unpatched /cube here would start a real build in the suite.
    monkeypatch.setattr(service, "cube_state", lambda *args, **kwargs: (dict(MANIFEST), "hit"))

    responses = [
        client.get("/targets"),
        client.get("/frames", params={"target": "r_dra", "band": "D1"}),
        client.get(
            "/preview",
            params={"obs_id": "obs-a", "ra": 248.16775, "dec": 66.75497, "band": "D1", "size": 0.3},
        ),
        client.get("/cube", params={"ra": 1, "dec": 2}),
        client.get("/healthz"),
    ]

    for response in responses:
        assert "fits" not in response.headers.get("content-type", "").lower()
