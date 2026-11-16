"""`/queue`: the builds in flight, read from the progress files the jobs already write.

Nothing here starts a build. The registry is a directory of `progress.json` files, so what is worth
testing is the filtering: a live job is listed, a dead or finished one is not, and a half-written file
is skipped instead of taking the page down.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.app import main


def _stamp(seconds_ago: float) -> str:
    moment = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    return moment.isoformat(timespec="seconds")


def _write(
    root: Path,
    key: str,
    *,
    seconds_ago: float = 1.0,
    **fields,
) -> None:
    directory = root / "cubes" / key
    directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "state": "building",
        "stage": "rendering_planes",
        "planes_done": 3,
        "planes_total": 102,
        "bytes_done": 12_000_000,
        "bytes_total": 306_000_000,
        "started_at": _stamp(seconds_ago + 5),
        "updated_at": _stamp(seconds_ago),
        "eta_seconds": 40,
        "message": "rendering planes",
        "planes": [{"index": 0, "file": "plane-000.webp"}],
        "points": [{"index": 0, "flux_mjy": 1.2}],
        "error": None,
        "ra": 269.45402,
        "dec": 4.69336,
        "name": "Barnard's Star",
    }
    payload.update(fields)
    (directory / "progress.json").write_text(json.dumps(payload))


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("API_CACHE_DIR", str(tmp_path))
    return TestClient(main.app)


def test_lists_a_building_job_without_its_planes(client: TestClient, tmp_path: Path) -> None:
    _write(tmp_path, "abc123")

    response = client.get("/queue")

    assert response.status_code == 200
    jobs = response.json()["jobs"]
    assert len(jobs) == 1
    job = jobs[0]
    assert job["key"] == "abc123"
    assert job["name"] == "Barnard's Star"
    assert job["ra"] == 269.45402
    assert job["dec"] == 4.69336
    assert job["state"] == "building"
    assert job["stage"] == "rendering_planes"
    assert job["planes_total"] == 102
    assert "planes" not in job and "points" not in job


def test_drops_a_job_whose_progress_stopped_moving(client: TestClient, tmp_path: Path) -> None:
    _write(tmp_path, "dead", seconds_ago=10_000)

    assert client.get("/queue").json()["jobs"] == []


def test_does_not_list_a_finished_job(client: TestClient, tmp_path: Path) -> None:
    _write(tmp_path, "done", state="done", stage="done")

    assert client.get("/queue").json()["jobs"] == []


def test_a_malformed_progress_file_is_skipped(client: TestClient, tmp_path: Path) -> None:
    broken = tmp_path / "cubes" / "broken"
    broken.mkdir(parents=True)
    (broken / "progress.json").write_text("{ this is not json")
    _write(tmp_path, "good")

    response = client.get("/queue")

    assert response.status_code == 200
    assert [job["key"] for job in response.json()["jobs"]] == ["good"]


def test_a_record_without_a_coordinate_is_skipped(client: TestClient, tmp_path: Path) -> None:
    _write(tmp_path, "old", ra=None, dec=None)

    assert client.get("/queue").json()["jobs"] == []


def test_an_empty_cache_is_an_empty_list(client: TestClient) -> None:
    response = client.get("/queue")

    assert response.status_code == 200
    assert response.json() == {"jobs": []}
    assert response.headers["Cache-Control"] == "no-store"


def test_newest_job_comes_first(client: TestClient, tmp_path: Path) -> None:
    _write(tmp_path, "older", seconds_ago=60)
    _write(tmp_path, "newer", seconds_ago=1)

    assert [job["key"] for job in client.get("/queue").json()["jobs"]] == ["newer", "older"]
