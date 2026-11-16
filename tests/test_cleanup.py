"""Deleting the raw downloads, and the three ways that could go wrong.

The guard is the point: a list of paths that happens to contain a WebP must not delete it, and a file
that has already been consumed must not turn into an error.
"""

from pathlib import Path

from pipeline.cleanup import delete_raw


def make(path: Path, size: int = 16) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path


def test_it_deletes_the_listed_files_and_counts_their_bytes(tmp_path):
    first = make(tmp_path / "a.fits", 40)
    second = make(tmp_path / "b.fits", 60)

    freed = delete_raw([first, second])

    assert freed == 100
    assert not first.exists()
    assert not second.exists()


def test_a_missing_file_is_not_an_error(tmp_path):
    present = make(tmp_path / "present.fits", 10)

    freed = delete_raw([present, tmp_path / "already-gone.fits"])

    assert freed == 10


def test_anything_that_is_not_raw_is_refused(tmp_path):
    """A mistaken list must not take a rendered frame, a manifest or a progress file with it."""
    webp = make(tmp_path / "frame.webp")
    manifest = make(tmp_path / "manifest.json")
    progress = make(tmp_path / "progress.json")

    freed = delete_raw([webp, manifest, progress])

    assert freed == 0
    assert webp.exists() and manifest.exists() and progress.exists()


def test_a_partial_download_is_raw_too(tmp_path):
    partial = make(tmp_path / "tile.part")

    assert delete_raw([partial]) == 16
    assert not partial.exists()


def test_the_same_path_twice_is_counted_once(tmp_path):
    path = make(tmp_path / "a.fits", 32)

    assert delete_raw([path, Path(str(path))]) == 32


def test_a_directory_is_skipped_rather_than_raising(tmp_path):
    directory = tmp_path / "dir.fits"
    directory.mkdir()

    assert delete_raw([directory]) == 0
    assert directory.is_dir()
