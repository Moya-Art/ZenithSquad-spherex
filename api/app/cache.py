"""Disk cache for live builds, behind an interface Phase 8 can point at a bucket.

Two keys, because the two questions are different:

* `sequence_key` answers "has this coordinate, band and field size already been built?" — it holds
  the manifest and every WebP of that sequence, so a repeat visit is a file read instead of a fresh
  round trip to IRSA and a re-download.
* `frame_key` is the build plan's `sha1(f"{obs_id}:{ra:.5f}:{dec:.5f}:{size}")` and holds one WebP,
  so `/preview` can answer for a single exposure even when the sequence entry is gone.

Five decimals is about an arcsecond, so a second click at the same coordinate lands on the same entry
and a click a degree away does not. That rounding is the point, and it has a test.

The disk is a working directory, not the record. On Cloud Run it dies with the instance, so every
write is also published to the object store (`api.app.store`) and every local miss is read back from
it. Object names are the path relative to this cache's root, so there is one naming rule and no second
layout to keep in step. With `GCS_BUCKET` unset the store is a no-op and this file behaves exactly as
it did before the bucket existed.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import threading
import time
from pathlib import Path

from api.app.store import LocalStore, default_store

_log = logging.getLogger(__name__)

# The page polls a building cube every two seconds, so uploading progress faster than that buys
# nothing but bucket writes and latency.
PROGRESS_UPLOAD_SECONDS = 2.0

DEFAULT_ROOT = "data/cache/api"

# Bumped whenever the rendered pixels change (a new stretch, a new encoder setting). It is part of
# every key, so old entries stop being reachable instead of being served with the old contrast — a
# cache that answers with the previous renderer makes a rendering fix look broken.
RENDER_VERSION = 2


def _digest(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:20]


def sequence_key(ra: float, dec: float, band: str, size_deg: float) -> str:
    # The field size is formatted too: 0.3 and 0.30 are the same request and must not be two entries.
    return _digest(f"v{RENDER_VERSION}:{ra:.5f}:{dec:.5f}:{band}:{size_deg:.3f}")


def frame_key(obs_id: str, ra: float, dec: float, size_deg: float) -> str:
    return _digest(f"v{RENDER_VERSION}:{obs_id}:{ra:.5f}:{dec:.5f}:{size_deg:.3f}")


def cube_key(ra: float, dec: float, size_deg: float) -> str:
    """No band: a cube is the whole spectrum at one position, which is the point of it."""
    return _digest(f"v{RENDER_VERSION}:{ra:.5f}:{dec:.5f}:{size_deg:.3f}")


class Cache:
    """A directory of sequences and single frames. No expiry: an `obs_id` never changes."""

    def __init__(self, root: str | Path | None = None, store=None) -> None:
        self.root = Path(root if root is not None else os.environ.get("API_CACHE_DIR", DEFAULT_ROOT))
        self.store = default_store() if store is None else store
        self._uploads: dict[str, float] = {}
        self._uploads_lock = threading.Lock()

    # --- the store -----------------------------------------------------------------------------

    def _name(self, path: Path) -> str:
        """The object name of a file: its path relative to the cache root. One naming rule."""
        return path.relative_to(self.root).as_posix()

    def _publish(self, path: Path, data: bytes) -> None:
        if not self.store.enabled:
            return
        try:
            self.store.put_bytes(self._name(path), data)
        except Exception as error:  # noqa: BLE001 - durability is not a reason to fail a request
            _log.warning("could not publish %s: %s", self._name(path), error)

    def _publish_throttled(self, path: Path, data: bytes) -> None:
        """A build's progress moves several times a second; the page polls every two."""
        name = self._name(path)
        now = time.monotonic()
        with self._uploads_lock:
            if now - self._uploads.get(name, 0.0) < PROGRESS_UPLOAD_SECONDS:
                return
            self._uploads[name] = now
        self._publish(path, data)

    def _read_bytes(self, path: Path) -> bytes | None:
        try:
            return path.read_bytes()
        except FileNotFoundError:
            pass
        data = self.store.get_bytes(self._name(path))
        if data is not None:
            self._write(path, data)
        return data

    def _read_json(self, path: Path) -> dict | None:
        try:
            return json.loads(path.read_text())
        except FileNotFoundError:
            pass
        except json.JSONDecodeError:
            # A half-written local file is a local bug; answering from the bucket would hide it.
            return None
        data = self.store.get_bytes(self._name(path))
        if data is None:
            return None
        self._write(path, data)
        try:
            return json.loads(data)
        except json.JSONDecodeError:
            return None

    def ensure_local(self, path: Path) -> Path:
        """A file a route is about to read, fetched from the store if this instance never wrote it."""
        if path.exists():
            return path
        data = self.store.get_bytes(self._name(path))
        if data is None:
            raise FileNotFoundError(path)
        self._write(path, data)
        return path

    def publish_sequence(self, key: str) -> int:
        return self._publish_dir(self.sequence_dir(key))

    def publish_cube(self, key: str) -> int:
        return self._publish_dir(self.cube_dir(key))

    def _publish_dir(self, directory: Path) -> int:
        """Upload an artifact that just finished building. Never called on a failure."""
        if not self.store.enabled or not directory.is_dir():
            return 0
        items = [
            (self._name(path), path.read_bytes())
            for path in sorted(directory.rglob("*"))
            if path.is_file()
        ]
        uploaded = self.store.put_many(items)
        _log.info("published %d of %d objects for %s", uploaded, len(items), directory)
        return uploaded

    # --- sequences -----------------------------------------------------------------------------

    def sequence_dir(self, key: str) -> Path:
        """Where `build_from_position` writes this sequence (`out_root`)."""
        return self.root / "seq" / key

    def manifest(self, key: str) -> dict | None:
        return self._read_json(self.sequence_dir(key) / "manifest.json")

    def put_manifest(self, key: str, manifest: dict) -> None:
        path = self.sequence_dir(key) / "manifest.json"
        data = json.dumps(manifest).encode("utf-8")
        self._write(path, data)
        self._publish(path, data)

    def frame_path(self, key: str, filename: str) -> Path:
        # `build_from_position` appends `/sequence` to the root it is given.
        return self.sequence_dir(key) / "sequence" / filename

    # --- single frames -------------------------------------------------------------------------

    def frame(self, key: str) -> bytes | None:
        return self._read_bytes(self.root / "frames" / f"{key}.webp")

    def put_frame(self, key: str, data: bytes) -> None:
        path = self.root / "frames" / f"{key}.webp"
        self._write(path, data)
        self._publish(path, data)

    # --- cubes ---------------------------------------------------------------------------------

    def cube_dir(self, key: str) -> Path:
        """Where `build_cube` writes this cube (`out_root`)."""
        return self.root / "cubes" / key

    def cube_manifest(self, key: str) -> dict | None:
        return self._read_json(self.cube_dir(key) / "cube.json")

    def put_cube_manifest(self, key: str, manifest: dict) -> None:
        path = self.cube_dir(key) / "cube.json"
        data = json.dumps(manifest).encode("utf-8")
        self._write(path, data)
        self._publish(path, data)

    def cube_file(self, key: str, filename: str) -> Path:
        # `build_cube` appends `/cube` to the root it is given.
        return self.cube_dir(key) / "cube" / filename

    def progress(self, key: str) -> dict | None:
        """The job registry. It lives on disk so any instance can answer for a build started on
        another one, and so a restart does not lose a finished result."""
        return self._read_json(self.cube_dir(key) / "progress.json")

    def put_progress(self, key: str, progress: dict) -> None:
        path = self.cube_dir(key) / "progress.json"
        data = json.dumps(progress).encode("utf-8")
        self._write(path, data)
        # A finished or failed job is published at once. A restarted instance that read a two-second-old
        # "building" would keep a dead job on the queue until the staleness timeout.
        if progress.get("state") in ("done", "failed"):
            self._publish(path, data)
        else:
            self._publish_throttled(path, data)

    # --- health --------------------------------------------------------------------------------

    def writable(self) -> bool:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=self.root, prefix=".probe-", delete=True):
                pass
            return True
        except OSError:
            return False

    @staticmethod
    def _write(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic: a killed build must not leave a half-written manifest that reads as a cache hit.
        descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
            os.replace(temporary, path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise
