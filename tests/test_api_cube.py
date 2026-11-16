"""The cube routes, with the build patched out.

A real cold cube is a 306 MiB download, so nothing here may reach the pipeline: every test monkeypatches
at the `service` boundary, which is the convention `test_api_routes.py` already uses for `/frames`.
"""

import shutil

import pytest
from conftest import FakeStore
from fastapi.testclient import TestClient

from api.app import cache as cache_module
from api.app import main, service

WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 "

BUILDING = {
    "state": "building",
    "stage": "rendering_planes",
    "message": "Rendering plane 41 of 102 (2.292 um)",
    "progress": {
        "planes_done": 41,
        "planes_total": 102,
        "bytes_done": 320909760,
        "bytes_total": 320909760,
        "started_at": "2026-11-15T22:44:23+00:00",
        "updated_at": "2026-11-15T22:45:02+00:00",
        "eta_seconds": 38,
    },
    "planes": [{"index": 0, "band": "D1", "channel": 1, "wavelength_um": 0.753}],
    "spectrum": {"unit": "mJy", "points": [{"index": 0, "flux_mjy": 666.0}]},
    "composite": None,
    "keeps_running": True,
}

READY = {
    "state": "ready",
    "target": "r_dra",
    "name": "R Draconis",
    "ra": 248.167375,
    "dec": 66.755014,
    "size_deg": 0.3,
    "planes": [],
    "spectrum": {"unit": "mJy", "points": []},
}


@pytest.fixture()
def client():
    return TestClient(main.app)


def test_a_committed_target_answers_without_queueing(client, monkeypatch):
    calls = []

    def state(*args, **kwargs):
        calls.append(kwargs)
        return dict(READY), "committed"

    monkeypatch.setattr(service, "cube_state", state)

    response = client.get("/cube", params={"target": "r_dra"})

    assert response.status_code == 200
    assert response.headers["x-cache"] == "committed"
    assert response.json()["state"] == "ready"
    assert calls[0]["size_deg"] == service.DEFAULT_SIZE_DEG


def test_a_cold_coordinate_answers_202_with_progress_and_a_retry_after(client, monkeypatch):
    monkeypatch.setattr(service, "cube_state", lambda *args, **kwargs: (dict(BUILDING), "building"))

    response = client.get("/cube", params={"ra": 90, "dec": 20, "size": 0.3})

    assert response.status_code == 202
    assert response.headers["retry-after"] == str(main.BUILD_POLL_SECONDS)
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["state"] == "building"
    assert body["progress"]["eta_seconds"] == 38
    # The planes that exist travel with the poll, which is what makes progressive rendering possible.
    assert len(body["planes"]) == 1


def test_a_failed_build_is_reported_and_never_cached(client, monkeypatch):
    payload = {
        "state": "failed",
        "error": {"reason": "archive_unreachable", "detail": "IRSA did not answer"},
        "message": "IRSA did not answer",
    }
    monkeypatch.setattr(service, "cube_state", lambda *args, **kwargs: (dict(payload), "failed"))

    response = client.get("/cube", params={"ra": 90, "dec": 20})

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["error"]["reason"] == "archive_unreachable"


def test_a_cube_needs_a_target_or_both_coordinates(client):
    assert client.get("/cube").status_code == 422
    assert client.get("/cube", params={"dec": 20}).status_code == 422
    assert client.get("/cube/plane", params={"plane": 3, "ra": 10}).status_code == 422


def test_an_unknown_target_is_404(client):
    assert client.get("/cube", params={"target": "not_a_target"}).status_code == 404


def test_a_plane_that_is_not_built_yet_is_404(client, monkeypatch):
    def not_ready(*args, **kwargs):
        raise service.CubeNotReady("plane 99 is not built yet")

    monkeypatch.setattr(service, "cube_plane_webp", not_ready)

    response = client.get("/cube/plane", params={"target": "r_dra", "plane": 99})

    assert response.status_code == 404
    assert "not built yet" in response.json()["detail"]


def test_a_plane_is_an_immutable_webp_with_an_etag(client, monkeypatch):
    monkeypatch.setattr(service, "cube_plane_webp", lambda *args, **kwargs: (WEBP, "committed"))

    response = client.get("/cube/plane", params={"target": "r_dra", "plane": 8})

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/webp"
    assert "immutable" in response.headers["cache-control"]
    etag = response.headers["etag"]

    again = client.get(
        "/cube/plane", params={"target": "r_dra", "plane": 8},
        headers={"If-None-Match": etag},
    )
    assert again.status_code == 304


def test_the_composite_is_also_webp(client, monkeypatch):
    monkeypatch.setattr(service, "cube_composite_webp", lambda *args, **kwargs: (WEBP, "hit"))

    response = client.get("/cube/composite", params={"ra": 90, "dec": 20})

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/webp"
    assert response.headers["x-cache"] == "hit"


def test_the_composite_is_404_until_every_plane_exists(client, monkeypatch):
    def not_ready(*args, **kwargs):
        raise service.CubeNotReady("the composite is not built yet")

    monkeypatch.setattr(service, "cube_composite_webp", not_ready)

    assert client.get("/cube/composite", params={"ra": 90, "dec": 20}).status_code == 404


def test_building_payload_publishes_only_what_exists():
    payload = service._building_payload({
        "state": "building",
        "stage": "rendering_planes",
        "planes_done": 2,
        "planes_total": 102,
        "planes": [{"index": 0}, {"index": 1}],
        "points": [{"index": 0}, {"index": 1}],
        "started_at": "2026-11-15T22:44:23+00:00",
        "updated_at": "2026-11-15T22:44:30+00:00",
        "eta_seconds": 41,
        "message": "Rendering",
    })

    assert payload["state"] == "building"
    assert len(payload["planes"]) == 2
    assert payload["composite"] is None
    assert payload["keeps_running"] is True


def test_a_stale_stamp_counts_as_dead():
    assert service._age_seconds("2000-01-01T00:00:00+00:00") > service.CUBE_STALE_SECONDS
    assert service._age_seconds(None) == float("inf")
    assert service._age_seconds("not a date") == float("inf")


@pytest.fixture()
def build_env(tmp_path, monkeypatch):
    """A cache and a tile directory in tmp_path, so a stubbed build never touches the real ones."""
    monkeypatch.setenv("API_CACHE_DIR", str(tmp_path / "api"))
    monkeypatch.setattr(service, "CUBE_TILE_DIR", tmp_path / "tiles")
    return tmp_path / "tiles" / "hips_x_N5_10226.fits"


def test_a_finished_cube_build_deletes_the_tile_it_used(build_env, monkeypatch):
    tile = build_env

    def fake_build(request, progress=None, raw_paths=None):
        tile.parent.mkdir(parents=True, exist_ok=True)
        tile.write_bytes(b"x" * 500)
        raw_paths.append(tile)
        return {"planes": [], "depth": 0, "spectrum": {"points": []}}

    monkeypatch.setattr(service.cube, "build_cube", fake_build)

    service._run_cube_job("key-a", service.position_for(90.0, 20.0, None), 0.3, False)

    assert not tile.exists()
    assert list(tile.parent.glob("*.fits")) == []
    progress = service.Cache().progress("key-a")
    assert progress["state"] == "done"
    assert progress["bytes_freed"] == 500


def test_a_failed_cube_build_keeps_what_it_downloaded(build_env, monkeypatch):
    """Debugging an archive failure needs the file that failed. Only success deletes."""
    tile = build_env

    def fake_build(request, progress=None, raw_paths=None):
        tile.parent.mkdir(parents=True, exist_ok=True)
        tile.write_bytes(b"x" * 500)
        raw_paths.append(tile)
        raise ValueError("the frames do not overlap")

    monkeypatch.setattr(service.cube, "build_cube", fake_build)

    service._run_cube_job("key-a", service.position_for(90.0, 20.0, None), 0.3, False)

    assert tile.exists()
    progress = service.Cache().progress("key-a")
    assert progress["state"] == "failed"
    assert "bytes_freed" not in progress


def test_a_plane_survives_the_instance_that_built_it(tmp_path, monkeypatch):
    """A new instance starts with an empty disk, so a plane must come from the store — one plane, not
    the cube's 103 files, because hydrating an artifact on every request is the cost this avoids."""
    store = FakeStore()
    monkeypatch.setenv("API_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(cache_module, "default_store", lambda: store)

    key = service.cube_key(248.16, 66.75, 0.3)
    builder = service.Cache()
    builder.put_cube_manifest(key, {
        "composite": {"file": "rgb.webp"},
        "planes": [{"index": 7, "file": "plane_007.webp"}],
    })
    plane = builder.cube_file(key, "plane_007.webp")
    plane.parent.mkdir(parents=True, exist_ok=True)
    plane.write_bytes(WEBP)
    builder.publish_cube(key)

    shutil.rmtree(tmp_path)  # the instance died and took /tmp with it
    tmp_path.mkdir()

    data, state = service.cube_plane_webp(7, 248.16, 66.75, 0.3)

    assert data == WEBP
    assert state == "hit"
    assert [name for name in store.gets if name.endswith(".webp")] == [
        f"cubes/{key}/cube/plane_007.webp"
    ]


def _coordinate_cube(target="ra269.4540_dec4.6934"):
    return {
        "target": target,
        "ra": 269.45402,
        "dec": 4.69336,
        "size_deg": 0.3,
        "planes": [{"index": 92, "file": "cube_plane_092.webp"}],
        "composite": {"file": "cube_rgb.webp"},
    }


def test_a_coordinate_cube_does_not_hand_out_its_label_as_a_target():
    """A cube built for a bare coordinate carries `ra269.4540_dec4.6934` as its display target. The
    routes validate `target` as a slug from /targets, so passing it on made all 102 plane URLs a 422
    the API generated for its own browser."""
    decorated = service._decorate_cube(_coordinate_cube(), "hit")

    assert "target=" not in decorated["planes"][0]["url"]
    assert "target=" not in decorated["composite"]["url"]
    # The label is still what the page shows; only the query parameter is wrong for it.
    assert decorated["target"] == "ra269.4540_dec4.6934"


def test_a_committed_cube_still_carries_its_slug():
    decorated = service._decorate_cube(_coordinate_cube(target="barnard"), "committed")

    assert "target=barnard" in decorated["planes"][0]["url"]
    assert "target=barnard" in decorated["composite"]["url"]


def test_the_urls_a_cube_hands_out_are_addressable(client):
    """The invariant behind the 422s: whatever this decorator emits must not be rejected by the
    router that serves it. A 404 means "not built yet" and is fine; 422 means it was never reachable."""
    decorated = service._decorate_cube(_coordinate_cube(), "hit")

    for url in (decorated["planes"][0]["url"], decorated["composite"]["url"]):
        assert client.get(url).status_code != 422, url
