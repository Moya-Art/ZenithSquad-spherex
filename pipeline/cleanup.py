"""Delete the raw downloads a build has already consumed.

The raw FITS files are ingredients, not deliverables: a 306 MiB all-sky tile and ~4 MB per date are
paid once so the WebPs and manifests can exist, and nothing in the API reads them again. Keeping them
forever is what turns a 300 GB budget into a few hundred looked-at coordinates.

Two rules make this safe to call from a live server:

* **Explicit paths, never a glob.** A glob under the cache would delete a different build's inputs.
* **Raw suffixes only.** Anything that is not a `.fits`/`.part` download is refused, so a mistaken
  list cannot take a WebP, a manifest or a `progress.json` with it.

A missing file is not an error — the same tile can be consumed by two builds — and a failed unlink is
skipped rather than turned into a build failure.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

RAW_SUFFIXES = frozenset({".fits", ".fit", ".part"})


def delete_raw(paths: Iterable[str | Path]) -> int:
    """Unlink each raw download that exists; return the bytes freed."""
    freed = 0
    for path in {Path(item) for item in paths}:
        if path.suffix.lower() not in RAW_SUFFIXES:
            continue
        try:
            size = path.stat().st_size
            path.unlink()
        except OSError:
            continue
        freed += size
    return freed
