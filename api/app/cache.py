"""Disk cache for live builds, behind an interface Phase 8 can point at a bucket.

Two keys, because the two questions are different:

* `sequence_key` answers "has this coordinate, band and field size already been built?" — it holds
  the manifest and every WebP of that sequence, so a repeat visit is a file read instead of a fresh
  round trip to IRSA and a re-download.
* `frame_key` is the build plan's `sha1(f"{obs_id}:{ra:.5f}:{dec:.5f}:{size}")` and holds one WebP,
  so `/preview` can answer for a single exposure even when the sequence entry is gone.

Five decimals is about an arcsecond, so a second click at the same coordinate lands on the same entry
and a click a degree away does not. That rounding is the point, and it has a test.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

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

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root if root is not None else os.environ.get("API_CACHE_DIR", DEFAULT_ROOT))

    # --- sequences -----------------------------------------------------------------------------

    def sequence_dir(self, key: str) -> Path:
        """Where `build_from_position` writes this sequence (`out_root`)."""
        return self.root / "seq" / key

    def manifest(self, key: str) -> dict | None:
        path = self.sequence_dir(key) / "manifest.json"
        try:
            return json.loads(path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    def put_manifest(self, key: str, manifest: dict) -> None:
        self._write(self.sequence_dir(key) / "manifest.json", json.dumps(manifest).encode("utf-8"))

    def frame_path(self, key: str, filename: str) -> Path:
        # `build_from_position` appends `/sequence` to the root it is given.
        return self.sequence_dir(key) / "sequence" / filename

    # --- single frames -------------------------------------------------------------------------

    def frame(self, key: str) -> bytes | None:
        try:
            return (self.root / "frames" / f"{key}.webp").read_bytes()
        except FileNotFoundError:
            return None

    def put_frame(self, key: str, data: bytes) -> None:
        self._write(self.root / "frames" / f"{key}.webp", data)

    # --- cubes ---------------------------------------------------------------------------------

    def cube_dir(self, key: str) -> Path:
        """Where `build_cube` writes this cube (`out_root`)."""
        return self.root / "cubes" / key

    def cube_manifest(self, key: str) -> dict | None:
        try:
            return json.loads((self.cube_dir(key) / "cube.json").read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    def put_cube_manifest(self, key: str, manifest: dict) -> None:
        self._write(self.cube_dir(key) / "cube.json", json.dumps(manifest).encode("utf-8"))

    def cube_file(self, key: str, filename: str) -> Path:
        # `build_cube` appends `/cube` to the root it is given.
        return self.cube_dir(key) / "cube" / filename

    def progress(self, key: str) -> dict | None:
        """The job registry. It lives on disk so any instance can answer for a build started on
        another one, and so a restart does not lose a finished result."""
        try:
            return json.loads((self.cube_dir(key) / "progress.json").read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    def put_progress(self, key: str, progress: dict) -> None:
        self._write(
            self.cube_dir(key) / "progress.json", json.dumps(progress).encode("utf-8")
        )

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
