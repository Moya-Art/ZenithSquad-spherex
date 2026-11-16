"""Live builds: the API's only door into `pipeline`.

A cold request is the expensive one. `/frames` does not merely list epochs — it builds the whole
sequence (SIA query, one cutout per date, one global stretch, one WebP per date) so that every frame
shares a single `vmin`/`vmax`. Listing epochs and stretching each frame on demand would manufacture
the fake variability BUILD_PLAN §4 calls the worst bug this project can ship.

Two guards keep that cost bounded:

* `_BUILD_LOCK` serialises cold builds. Cloud Run runs several requests concurrently and each build
  fans out to eight download workers; four builds in parallel would sail past IRSA's ~12-request
  limit. A second visitor waits for the first build instead of doubling the load.
* FITS files go to `data/cache/`, the same directory the CLI uses, so a coordinate the pipeline has
  already touched costs no downloads at all.

Nothing here knows about HTTP. `api.app.main` maps exceptions to status codes.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

from pipeline import catalog, cleanup, cube
from pipeline.sequence import PositionSpec, build_from_position, pick_band

from api.app.cache import Cache, cube_key, frame_key, sequence_key

_log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
TARGETS_PATH = Path(os.environ.get("TARGETS_PATH", REPO_ROOT / "data" / "targets.json"))
FITS_CACHE_DIR = Path(os.environ.get("FITS_CACHE_DIR", REPO_ROOT / "data" / "cache"))
CUBE_TILE_DIR = Path(os.environ.get("TILE_CACHE_DIR", REPO_ROOT / "data" / "cache" / "cube_tiles"))
CUBE_FALLBACK_DIR = Path(
    os.environ.get("CUBE_FALLBACK_DIR", REPO_ROOT / "data" / "fallback" / "cube")
)
COLLECTION = os.environ.get("SPHEREX_COLLECTION", "spherex_dr1")

DEFAULT_SIZE_DEG = 0.3
IMMUTABLE_SECONDS = 604800
# A job whose progress has not moved for this long is dead, not slow: the worker thread died with the
# process, or another instance owned it. The next visitor re-enqueues instead of waiting forever.
CUBE_STALE_SECONDS = 120.0
CUBE_PROGRESS_WRITE_SECONDS = 0.4

_BUILD_LOCK = threading.Semaphore(1)
_irsa_contact: str | None = None

_cube_queue: "queue.Queue[tuple]" = queue.Queue()
_cube_jobs: set[str] = set()
_cube_jobs_lock = threading.Lock()
_cube_worker_started = False


class NoCoverage(RuntimeError):
    """The archive answered, and the answer was zero frames. A result, not an outage."""


class UnknownFrame(RuntimeError):
    """The `obs_id` is not part of that coordinate's sequence."""


class CubeNotReady(RuntimeError):
    """That plane is not on disk yet. A 404 that means "still building", not a failure."""


def targets() -> list[dict]:
    return json.loads(TARGETS_PATH.read_text())["targets"]


def find_target(slug: str) -> dict | None:
    return next((item for item in targets() if item["slug"] == slug), None)


def note_irsa_contact() -> None:
    global _irsa_contact
    _irsa_contact = datetime.now(timezone.utc).isoformat(timespec="seconds")


def last_irsa_contact() -> str | None:
    return _irsa_contact


def coordinate_label(ra: float, dec: float) -> str:
    return f"ra{ra:.4f}_dec{dec:.4f}"


def position_fields(position: PositionSpec) -> dict:
    """The bits of a position every progress record carries.

    They live on disk because the cache key is a hash: `/queue` lists jobs by walking
    `cubes/*/progress.json`, and without these three fields a job could not say what sky it is for.
    """
    return {
        "ra": round(position.ra, 6),
        "dec": round(position.dec, 6),
        "name": position.name,
    }


def position_for(ra: float, dec: float, target: str | None) -> PositionSpec:
    """A named target keeps its proper motion; a typed coordinate has none and says so."""
    if target:
        entry = find_target(target)
        if entry is not None:
            return PositionSpec(
                ra=ra,
                dec=dec,
                label=entry["slug"],
                name=entry.get("name", entry["slug"]),
                pm_ra_cosdec=entry.get("pm_ra_cosdec"),
                pm_dec=entry.get("pm_dec"),
            )
    return PositionSpec(
        ra=ra,
        dec=dec,
        label=coordinate_label(ra, dec),
        name=f"RA {ra:.4f} Dec {dec:+.4f}",
    )


def resolve_band(
    ra: float, dec: float, band: str | None, collection: str = COLLECTION
) -> str:
    """The band a request means. Omitted, it is the one with the most dates (BUILD_PLAN §1.2).

    Resolving it here, before the build, is what lets the cache key exist before anything is
    downloaded — it costs one extra SIA query only when the visitor did not name a band.
    """
    if band:
        return band

    summary = catalog.summarise(catalog.frames_from_rows(catalog.fetch_rows(ra, dec, collection)))
    if not summary.bands:
        raise NoCoverage(
            f"0 frames in {collection} at RA {ra:.5f} Dec {dec:.5f}: the archive answered, "
            "and this patch of sky has no coverage there"
        )
    return pick_band(summary.bands)


def preview_path(
    obs_id: str, ra: float, dec: float, band: str, size_deg: float
) -> str:
    query = urlencode(
        {
            "obs_id": obs_id,
            "ra": f"{ra:.6f}",
            "dec": f"{dec:.6f}",
            "band": band,
            "size": f"{size_deg:g}",
        }
    )
    return f"/preview?{query}"


def _decorate(manifest: dict, ra: float, dec: float, size_deg: float) -> dict:
    decorated = dict(manifest)
    decorated["source"] = "live"
    decorated["stale"] = False
    decorated["frames"] = [
        {
            **frame,
            "url": preview_path(frame["obs_id"], ra, dec, manifest["band"], size_deg),
        }
        for frame in manifest["frames"]
    ]
    return decorated


def cached_sequence(
    ra: float, dec: float, band: str, size_deg: float
) -> dict | None:
    manifest = Cache().manifest(sequence_key(ra, dec, band, size_deg))
    return None if manifest is None else _decorate(manifest, ra, dec, size_deg)


def _free_raw(raw: list[Path], key: str) -> int:
    """Delete the raw downloads a successful build consumed. Never called on a failure.

    A failed build keeps its FITS files: debugging an archive failure needs the download that
    failed. And this runs only after the manifest and the WebPs are on disk, so a crash between the
    two costs a re-download and gains nothing.
    """
    freed = cleanup.delete_raw(raw)
    if freed:
        _log.info("freed %d bytes of raw downloads for %s", freed, key)
    return freed


def live_sequence(
    ra: float,
    dec: float,
    band: str | None = None,
    size_deg: float = DEFAULT_SIZE_DEG,
    collection: str = COLLECTION,
    refresh: bool = False,
    target: str | None = None,
) -> tuple[dict, str]:
    """Return `(manifest, "miss"|"hit")`. Blocks on a cold key until the sequence exists."""
    cache = Cache()
    chosen = resolve_band(ra, dec, band, collection)
    key = sequence_key(ra, dec, chosen, size_deg)

    if not refresh:
        cached = cache.manifest(key)
        if cached is not None:
            return _decorate(cached, ra, dec, size_deg), "hit"

    held = _BUILD_LOCK.acquire(blocking=False)
    try:
        if not held:
            # A build is already running. Wait for it instead of multiplying IRSA traffic; the cache
            # is re-checked below, so a second visitor for the same coordinate usually buys nothing.
            _BUILD_LOCK.acquire()
        if not refresh:
            cached = cache.manifest(key)
            if cached is not None:
                return _decorate(cached, ra, dec, size_deg), "hit"

        raw: list[Path] = []
        manifest = build_from_position(
            position_for(ra, dec, target),
            collection=collection,
            band=chosen,
            size_deg=size_deg,
            out_root=cache.sequence_dir(key),
            cache_dir=FITS_CACHE_DIR,
            write_manifest=True,
            raw_paths=raw,
        )
        cache.put_manifest(key, manifest)
        _free_raw(raw, key)
        note_irsa_contact()
        return _decorate(manifest, ra, dec, size_deg), "miss"
    finally:
        _BUILD_LOCK.release()


def preview_webp(
    obs_id: str,
    ra: float,
    dec: float,
    band: str,
    size_deg: float = DEFAULT_SIZE_DEG,
    collection: str = COLLECTION,
) -> tuple[bytes, str]:
    """One frame as WebP, rendered with the sequence's own stretch. Never FITS."""
    cache = Cache()
    key = frame_key(obs_id, ra, dec, size_deg)
    cached = cache.frame(key)
    if cached is not None:
        return cached, "hit"

    manifest, state = live_sequence(
        ra, dec, band=band, size_deg=size_deg, collection=collection
    )
    frame = next((item for item in manifest["frames"] if item["obs_id"] == obs_id), None)
    if frame is None:
        raise UnknownFrame(
            f"{obs_id} is not in the {manifest['band']} sequence at RA {ra:.5f} Dec {dec:.5f}"
        )

    path = cache.frame_path(
        sequence_key(ra, dec, manifest["band"], size_deg), frame["file"]
    )
    data = path.read_bytes()
    cache.put_frame(key, data)
    return data, "miss"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _age_seconds(stamp: str | None) -> float:
    if not stamp:
        return float("inf")
    try:
        then = datetime.fromisoformat(stamp)
    except ValueError:
        return float("inf")
    return (datetime.now(timezone.utc) - then).total_seconds()


def cube_plane_path(index: int, ra: float, dec: float, size_deg: float,
                    target: str | None = None) -> str:
    params = {
        "ra": f"{ra:.6f}",
        "dec": f"{dec:.6f}",
        "size": f"{size_deg:g}",
        "plane": index,
    }
    if target:
        params["target"] = target
    return f"/cube/plane?{urlencode(params)}"


def cube_composite_path(ra: float, dec: float, size_deg: float,
                        target: str | None = None) -> str:
    params = {"ra": f"{ra:.6f}", "dec": f"{dec:.6f}", "size": f"{size_deg:g}"}
    if target:
        params["target"] = target
    return f"/cube/composite?{urlencode(params)}"


def _decorate_cube(manifest: dict, source: str) -> dict:
    """Add the URLs a browser needs. The committed artifact has the same shape, so one decorator
    serves a committed cube, a cached one and a half-built one."""
    decorated = dict(manifest)
    decorated["source"] = source
    ra, dec = manifest.get("ra"), manifest.get("dec")
    size_deg = manifest.get("size_deg", DEFAULT_SIZE_DEG)
    target = manifest.get("target")
    if ra is None or dec is None:
        return decorated
    decorated["planes"] = [
        {**plane, "url": cube_plane_path(plane["index"], ra, dec, size_deg, target)}
        for plane in manifest.get("planes", [])
    ]
    if manifest.get("composite"):
        decorated["composite"] = {
            **manifest["composite"],
            "url": cube_composite_path(ra, dec, size_deg, target),
        }
    return decorated


def committed_cube(target: str, size_deg: float | None = None) -> dict | None:
    """A cube built by the CLI and committed. The five targets never queue, because this answers."""
    try:
        manifest = json.loads((CUBE_FALLBACK_DIR / f"{target}.json").read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    if size_deg is not None and abs(float(manifest.get("size_deg", -1)) - size_deg) > 1e-9:
        return None
    return _decorate_cube(manifest, "committed")


def _building_payload(progress: dict) -> dict:
    total = progress.get("planes_total")
    done = progress.get("planes_done") or 0
    return {
        "state": progress.get("state", "building"),
        "stage": progress.get("stage"),
        "message": progress.get("message"),
        "progress": {
            "planes_done": done,
            "planes_total": total,
            "bytes_done": progress.get("bytes_done"),
            "bytes_total": progress.get("bytes_total"),
            "started_at": progress.get("started_at"),
            "updated_at": progress.get("updated_at"),
            "eta_seconds": progress.get("eta_seconds"),
        },
        # Whatever exists already. This is what lets the page render plane 0 while plane 90 is still
        # being computed, instead of holding a spinner for the whole build.
        "planes": progress.get("planes", []),
        "spectrum": {"unit": "mJy", "points": progress.get("points", [])},
        "composite": None,
        "keeps_running": True,
    }


def _failed_payload(progress: dict) -> dict:
    error = progress.get("error") or {}
    return {
        "state": "failed",
        "stage": progress.get("stage"),
        "error": error,
        "message": error.get("detail") or "the cube build did not finish",
        "retry_with_refresh": True,
    }


def _ensure_cube_worker() -> None:
    global _cube_worker_started
    with _cube_jobs_lock:
        if _cube_worker_started:
            return
        thread = threading.Thread(target=_cube_worker_loop, name="cube-builder", daemon=True)
        thread.start()
        _cube_worker_started = True


def _cube_worker_loop() -> None:
    while True:
        job = _cube_queue.get()
        try:
            _run_cube_job(*job)
        except Exception:
            # `_run_cube_job` records its own failures; this only keeps the worker alive.
            pass
        finally:
            key = job[0]
            with _cube_jobs_lock:
                _cube_jobs.discard(key)
            _cube_queue.task_done()


def _run_cube_job(key: str, position: PositionSpec, size_deg: float, refresh: bool) -> None:
    cache = Cache()
    started = time.time()
    render_started: list[float | None] = [None]
    last_write = [0.0]
    collected: dict[str, list] = {"planes": [], "points": []}
    stage_seen: list[str | None] = [None]

    def publish(update: dict) -> None:
        stage = update.get("stage")
        if stage == "rendering_planes" and render_started[0] is None:
            render_started[0] = time.time()
        if "plane" in update:
            collected["planes"].append(update["plane"])
        if "point" in update:
            collected["points"].append(update["point"])

        now = time.time()
        done = update.get("planes_done") or 0
        total = update.get("planes_total")
        if stage == "rendering_planes" and done and render_started[0]:
            spent = max(now - render_started[0], 1e-6)
            eta = (total - done) * spent / done if total else None
        elif update.get("bytes_total") and update.get("bytes_done"):
            spent = max(now - started, 1e-6)
            eta = (update["bytes_total"] - update["bytes_done"]) * spent / max(
                update["bytes_done"], 1)
        else:
            eta = None

        changed = stage != stage_seen[0]
        if not changed and now - last_write[0] < CUBE_PROGRESS_WRITE_SECONDS:
            return
        stage_seen[0] = stage
        last_write[0] = now
        cache.put_progress(key, {
            "state": "building",
            "stage": stage,
            "planes_done": done,
            "planes_total": total,
            "bytes_done": update.get("bytes_done"),
            "bytes_total": update.get("bytes_total"),
            "started_at": datetime.fromtimestamp(started, timezone.utc).isoformat(
                timespec="seconds"),
            "updated_at": _now(),
            "eta_seconds": None if eta is None else int(round(eta)),
            "message": update.get("message"),
            "planes": collected["planes"],
            "points": collected["points"],
            "error": None,
            **position_fields(position),
        })

    try:
        raw: list[Path] = []
        manifest = cube.build_cube(
            cube.CubeRequest(
                position=position,
                size_deg=size_deg,
                out_root=cache.cube_dir(key),
                cache_dir=FITS_CACHE_DIR,
                tile_cache_dir=CUBE_TILE_DIR,
                refresh=refresh,
            ),
            progress=publish,
            raw_paths=raw,
        )
    except (catalog.ArchiveUnknown, catalog.SchemaError, cube.TileUnavailable) as error:
        note_irsa_contact()
        _record_failure(cache, key, started, "archive_unreachable", str(error), position)
        return
    except ValueError as error:
        _record_failure(cache, key, started, "cannot_build", str(error), position)
        return
    except Exception as error:  # noqa: BLE001 - reported, not swallowed
        _record_failure(cache, key, started, "internal", f"{type(error).__name__}: {error}",
                        position)
        return

    note_irsa_contact()
    cache.put_cube_manifest(key, manifest)
    freed = _free_raw(raw, key)
    cache.put_progress(key, {
        "state": "done",
        "stage": "done",
        "planes_done": len(manifest["planes"]),
        "planes_total": manifest["depth"],
        "started_at": datetime.fromtimestamp(started, timezone.utc).isoformat(
            timespec="seconds"),
        "updated_at": _now(),
        "eta_seconds": 0,
        "message": "Cube complete",
        "planes": manifest["planes"],
        "points": manifest["spectrum"]["points"],
        "error": None,
        "bytes_freed": freed,
        **position_fields(position),
    })


def _record_failure(cache: Cache, key: str, started: float, reason: str, detail: str,
                    position: PositionSpec) -> None:
    cache.put_progress(key, {
        "state": "failed",
        "stage": "failed",
        "planes_done": 0,
        "planes_total": None,
        "started_at": datetime.fromtimestamp(started, timezone.utc).isoformat(
            timespec="seconds"),
        "updated_at": _now(),
        "eta_seconds": None,
        "message": detail,
        "planes": [],
        "points": [],
        "error": {"reason": reason, "detail": detail, "at": _now()},
        **position_fields(position),
    })


def enqueue_cube(key: str, position: PositionSpec, size_deg: float, refresh: bool) -> None:
    """Queue a build, once. Two visitors asking for the same cold coordinate share one download."""
    with _cube_jobs_lock:
        if key in _cube_jobs:
            return
        _cube_jobs.add(key)
    Cache().put_progress(key, {
        "state": "queued",
        "stage": "queued",
        "planes_done": 0,
        "planes_total": None,
        "bytes_done": 0,
        "bytes_total": None,
        "started_at": _now(),
        "updated_at": _now(),
        "eta_seconds": None,
        "message": "Queued: this patch of sky has no cube yet.",
        "planes": [],
        "points": [],
        "error": None,
        **position_fields(position),
    })
    _ensure_cube_worker()
    _cube_queue.put((key, position, size_deg, refresh))


QUEUE_STATES = ("queued", "building", "failed")


def queue_state() -> list[dict]:
    """Every cube build this instance knows about, newest first.

    The job registry is already on disk — one `progress.json` per cache key — so this is a directory
    walk, not new storage. A finished job is not a queue item (it is a cache hit), a job whose
    `updated_at` stopped moving is dead and dropped, and a half-written file is skipped rather than
    turned into a 500.
    """
    cache = Cache()
    directory = cache.root / "cubes"
    if not directory.is_dir():
        return []

    jobs = []
    for entry in directory.iterdir():
        if not entry.is_dir():
            continue
        progress = cache.progress(entry.name)
        if progress is None or progress.get("state") not in QUEUE_STATES:
            continue
        if _age_seconds(progress.get("updated_at")) >= CUBE_STALE_SECONDS:
            continue
        ra, dec = progress.get("ra"), progress.get("dec")
        if ra is None or dec is None:
            continue
        jobs.append({
            "key": entry.name,
            "name": progress.get("name") or f"RA {ra:.4f} Dec {dec:+.4f}",
            "ra": ra,
            "dec": dec,
            "state": progress.get("state"),
            "stage": progress.get("stage"),
            "planes_done": progress.get("planes_done") or 0,
            "planes_total": progress.get("planes_total"),
            "bytes_done": progress.get("bytes_done"),
            "bytes_total": progress.get("bytes_total"),
            "eta_seconds": progress.get("eta_seconds"),
            "started_at": progress.get("started_at"),
            "updated_at": progress.get("updated_at"),
        })

    # ISO-8601 timestamps with one offset sort as text, which is what makes this a plain sort.
    jobs.sort(key=lambda job: job.get("updated_at") or "", reverse=True)
    return jobs


def cube_state(
    ra: float,
    dec: float,
    target: str | None = None,
    size_deg: float = DEFAULT_SIZE_DEG,
    refresh: bool = False,
) -> tuple[dict, str]:
    """Return `(payload, state)` for a cube request. `state` is one of
    committed / hit / building / failed.

    The order is deliberate: a committed artifact first (the five targets must never wait), then the
    cache, then a job. There is no synchronous build path — a 306 MiB tile download does not belong
    inside a request that a browser will time out on.
    """
    if target and not refresh:
        committed = committed_cube(target, size_deg)
        if committed is not None:
            return committed, "committed"

    cache = Cache()
    key = cube_key(ra, dec, size_deg)
    if not refresh:
        manifest = cache.cube_manifest(key)
        if manifest is not None:
            return _decorate_cube(manifest, "hit"), "hit"
        progress = cache.progress(key)
        if progress is not None:
            if progress.get("state") == "failed" and _age_seconds(
                    progress.get("updated_at")) < CUBE_STALE_SECONDS:
                return _failed_payload(progress), "failed"
            if progress.get("state") in ("queued", "building") and _age_seconds(
                    progress.get("updated_at")) < CUBE_STALE_SECONDS:
                if progress.get("state") == "queued":
                    # It is on the queue of *this* process or was claimed elsewhen; re-arming the
                    # worker is free and covers the case where the thread died with a reload.
                    enqueue_cube(key, position_for(ra, dec, target), size_deg, refresh)
                return _building_payload(progress), "building"

    enqueue_cube(key, position_for(ra, dec, target), size_deg, refresh)
    progress = cache.progress(key) or {}
    return _building_payload(progress), "building"


def cube_plane_webp(
    index: int, ra: float, dec: float, size_deg: float, target: str | None = None
) -> tuple[bytes, str]:
    """One plane as WebP. Missing means "not built yet", which is a 404 and not an error."""
    if target:
        committed = committed_cube(target, size_deg)
        if committed is not None:
            entry = next(
                (plane for plane in committed["planes"] if plane["index"] == index), None)
            if entry is not None:
                path = CUBE_FALLBACK_DIR / entry["file"]
                if path.exists():
                    return path.read_bytes(), "committed"
    cache = Cache()
    key = cube_key(ra, dec, size_deg)
    manifest = cache.cube_manifest(key)
    planes = manifest["planes"] if manifest else (
        (cache.progress(key) or {}).get("planes") or [])
    entry = next((plane for plane in planes if plane["index"] == index), None)
    if entry is None:
        raise CubeNotReady(f"plane {index} is not built yet")
    try:
        return cache.cube_file(key, entry["file"]).read_bytes(), "hit"
    except FileNotFoundError as error:
        raise CubeNotReady(f"plane {index} is not built yet") from error


def cube_composite_webp(
    ra: float, dec: float, size_deg: float, target: str | None = None
) -> tuple[bytes, str]:
    if target:
        committed = committed_cube(target, size_deg)
        if committed is not None:
            path = CUBE_FALLBACK_DIR / committed["composite"]["file"]
            if path.exists():
                return path.read_bytes(), "committed"
    cache = Cache()
    key = cube_key(ra, dec, size_deg)
    manifest = cache.cube_manifest(key)
    if manifest is None:
        raise CubeNotReady("the composite is written once every plane exists")
    try:
        return cache.cube_file(key, manifest["composite"]["file"]).read_bytes(), "hit"
    except FileNotFoundError as error:
        raise CubeNotReady("the composite is not built yet") from error


def health() -> dict:
    cache = Cache()
    try:
        count = len(targets())
        targets_state = "ok"
    except (OSError, KeyError, json.JSONDecodeError):
        count = 0
        targets_state = "unavailable"

    return {
        "status": "ok",
        "last_irsa_contact": _irsa_contact,
        "cache_writable": cache.writable(),
        "targets": count,
        "targets_state": targets_state,
        "collection": COLLECTION,
        "bucket_reachable": None,
    }
