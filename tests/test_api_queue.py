"""`GET /queue`: the on-disk cube job registry as a list.

Nothing here builds anything. The subject is the walk over `cubes/*/progress.json` and the two rules
that keep it honest: a finished job is not a queue item, and a job whose stamp stopped moving is dead.
"""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from api.app import main, service
from api.app.cache import Cache

NOW = datetime.now(timezone.utc).isoformat(timespec="seconds")
STALE = "2000-01-01T00:00:00+00:00"


@pytest.fixture()
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("API_CACHE_DIR", str(tmp_path))
    return Cache(tmp_path)


def record(cache: Cache, key: str, **fields) -> None:
    progress = {
        "state": "building",
        "stage": "rendering_planes",
        "planes_done": 41,
        "planes_total": 102,
        "bytes_done": 320909760,
        "bytes_total": 320909760,
        "started_at": NOW,
        "updated_at": NOW,
        "eta_seconds": 38,
        "ra": 90.0,
        "dec": 20.0,
        "name": "RA 90.0000 Dec +20.0000",
        # A real progress file carries these; a listing must not.
        "message": "rendering planes",
        "planes": [{"index": 0, "file": "plane-000.webp"}],
        "points": [{"index": 0, "flux_mjy": 1.2}],
    }
    progress.update(fields)
    cache.put_progress(key, progress)


def test_an_empty_cache_is_an_empty_queue(cache):
    assert service.queue_state() == []


def test_a_building_job_is_listed_with_what_a_visitor_needs(cache):
    record(cache, "key-a")

    [job] = service.queue_state()

    assert job["key"] == "key-a"
    assert job["state"] == "building"
    assert job["stage"] == "rendering_planes"
    assert job["planes_done"] == 41
    assert job["planes_total"] == 102
    assert job["eta_seconds"] == 38
    assert job["ra"] == 90.0
    assert job["dec"] == 20.0
    assert job["name"] == "RA 90.0000 Dec +20.0000"
    assert "planes" not in job and "points" not in job


def test_newest_first(cache):
    record(cache, "older", updated_at="2026-11-16T10:00:00+00:00")
    record(cache, "newer", updated_at="2026-11-16T11:00:00+00:00")

    assert [job["key"] for job in service.queue_state()] == ["newer", "older"]


def test_a_queued_job_is_listed_too(cache):
    record(cache, "key-a", state="queued", stage="queued", planes_done=0, planes_total=None)

    [job] = service.queue_state()

    assert job["state"] == "queued"
    assert job["planes_done"] == 0


def test_a_failed_job_stays_visible_because_someone_has_to_see_it(cache):
    record(cache, "key-a", state="failed", stage="failed")

    [job] = service.queue_state()

    assert job["state"] == "failed"


def test_a_finished_job_is_not_a_queue_item(cache):
    record(cache, "key-a", state="done", stage="done", eta_seconds=0)

    assert service.queue_state() == []


def test_a_stale_stamp_counts_as_dead_and_is_dropped(cache):
    record(cache, "key-a", updated_at=STALE)

    assert service.queue_state() == []


def test_a_missing_position_is_skipped_rather_than_guessed(cache):
    record(cache, "key-a", ra=None, dec=None)

    assert service.queue_state() == []


def test_a_half_written_file_does_not_break_the_list(cache):
    record(cache, "good")
    cache.cube_dir("broken").mkdir(parents=True)
    (cache.cube_dir("broken") / "progress.json").write_text('{"state": "build')

    assert [job["key"] for job in service.queue_state()] == ["good"]


def test_an_unknown_name_falls_back_to_the_coordinate(cache):
    record(cache, "key-a", name=None)

    assert service.queue_state()[0]["name"] == "RA 90.0000 Dec +20.0000"


def test_the_route_returns_the_jobs_it_is_given(monkeypatch):
    client = TestClient(main.app)
    monkeypatch.setattr(service, "queue_state", lambda: [{"key": "k", "state": "building"}])

    response = client.get("/queue")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"jobs": [{"key": "k", "state": "building"}]}


def test_the_route_answers_an_empty_list_on_a_fresh_instance(cache):
    response = TestClient(main.app).get("/queue")

    assert response.status_code == 200
    assert response.json() == {"jobs": []}
