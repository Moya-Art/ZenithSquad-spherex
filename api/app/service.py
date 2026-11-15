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
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

from pipeline import catalog
from pipeline.sequence import PositionSpec, build_from_position, pick_band

from api.app.cache import Cache, frame_key, sequence_key

REPO_ROOT = Path(__file__).resolve().parents[2]
TARGETS_PATH = Path(os.environ.get("TARGETS_PATH", REPO_ROOT / "data" / "targets.json"))
FITS_CACHE_DIR = Path(os.environ.get("FITS_CACHE_DIR", REPO_ROOT / "data" / "cache"))
COLLECTION = os.environ.get("SPHEREX_COLLECTION", "spherex_dr1")

DEFAULT_SIZE_DEG = 0.3
IMMUTABLE_SECONDS = 604800

_BUILD_LOCK = threading.Semaphore(1)
_irsa_contact: str | None = None


class NoCoverage(RuntimeError):
    """The archive answered, and the answer was zero frames. A result, not an outage."""


class UnknownFrame(RuntimeError):
    """The `obs_id` is not part of that coordinate's sequence."""


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

        manifest = build_from_position(
            position_for(ra, dec, target),
            collection=collection,
            band=chosen,
            size_deg=size_deg,
            out_root=cache.sequence_dir(key),
            cache_dir=FITS_CACHE_DIR,
            write_manifest=True,
        )
        cache.put_manifest(key, manifest)
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
