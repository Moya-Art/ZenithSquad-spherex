"""Cache keys and hit/miss verdicts. No network, no build — the filesystem is the subject."""

import json

from conftest import FakeStore

from api.app import cache as cache_module
from api.app.cache import Cache, cube_key, frame_key, sequence_key


def test_a_key_is_deterministic():
    assert sequence_key(248.16775, 66.75497, "D6", 0.3) == sequence_key(
        248.16775, 66.75497, "D6", 0.3
    )
    assert frame_key("2025W20_2D_0243_1", 248.16775, 66.75497, 0.3) == frame_key(
        "2025W20_2D_0243_1", 248.16775, 66.75497, 0.3
    )


def test_identical_clicks_beyond_the_fifth_decimal_share_an_entry():
    # Five decimals of a degree is 0.036 arcsec, so a re-click that differs in the sixth decimal is
    # the same request and must not build the sequence twice.
    assert sequence_key(248.167750, 66.754970, "D6", 0.3) == sequence_key(
        248.16775004, 66.75497004, "D6", 0.3
    )


def test_one_arcsecond_apart_is_a_different_entry():
    # 1 arcsec = 1/3600 deg = 0.00028 deg, which the fifth decimal does carry.
    assert sequence_key(10.0, 0.0, "D6", 0.3) != sequence_key(10.0 + 1 / 3600, 0.0, "D6", 0.3)


def test_a_field_size_written_two_ways_is_one_request():
    assert sequence_key(10.0, 0.0, "D6", 0.3) == sequence_key(10.0, 0.0, "D6", 0.30)


def test_band_and_size_are_part_of_the_key():
    base = sequence_key(10.0, 0.0, "D6", 0.3)
    assert base != sequence_key(10.0, 0.0, "D1", 0.3)
    assert base != sequence_key(10.0, 0.0, "D6", 0.2)


def test_the_render_version_is_part_of_every_key(monkeypatch):
    """A rendering change must retire every cached pixel, including the single frames `/preview`
    serves: those are never expired, so a stale one would outlive the fix."""
    before = (sequence_key(10.0, 0.0, "D6", 0.3), frame_key("obs", 10.0, 0.0, 0.3),
              cube_key(10.0, 0.0, 0.3))

    monkeypatch.setattr(cache_module, "RENDER_VERSION", cache_module.RENDER_VERSION + 1)
    after = (sequence_key(10.0, 0.0, "D6", 0.3), frame_key("obs", 10.0, 0.0, 0.3),
             cube_key(10.0, 0.0, 0.3))

    assert all(old != new for old, new in zip(before, after))


def test_a_manifest_is_a_miss_then_a_hit(tmp_path):
    cache = Cache(tmp_path)
    key = sequence_key(10.0, 0.0, "D6", 0.3)
    assert cache.manifest(key) is None

    cache.put_manifest(key, {"target": "x", "frames": []})

    assert cache.manifest(key) == {"target": "x", "frames": []}


def test_a_half_written_manifest_reads_as_a_miss_not_a_crash(tmp_path):
    cache = Cache(tmp_path)
    key = sequence_key(10.0, 0.0, "D6", 0.3)
    cache.sequence_dir(key).mkdir(parents=True)
    (cache.sequence_dir(key) / "manifest.json").write_text(json.dumps({"frames": []})[:5])

    assert cache.manifest(key) is None


def test_frames_are_a_miss_then_a_hit_and_land_where_sequence_frames_do(tmp_path):
    cache = Cache(tmp_path)
    key = frame_key("obs", 10.0, 0.0, 0.3)
    assert cache.frame(key) is None

    cache.put_frame(key, b"RIFF-webp")

    assert cache.frame(key) == b"RIFF-webp"
    assert cache.frame_path("seq", "x.webp") == tmp_path / "seq" / "seq" / "sequence" / "x.webp"


def test_the_cache_reports_whether_it_can_be_written(tmp_path):
    assert Cache(tmp_path / "fresh").writable() is True


# --- the bucket ---------------------------------------------------------------------------------


def test_a_manifest_is_published_under_its_path(tmp_path):
    store = FakeStore()
    key = sequence_key(10.0, 0.0, "D6", 0.3)

    Cache(tmp_path, store=store).put_manifest(key, {"frames": []})

    assert store.objects[f"seq/{key}/manifest.json"] == b'{"frames": []}'


def test_a_restarted_instance_answers_from_the_store(tmp_path):
    """The whole feature, in one assertion: an instance that never wrote this sequence still serves it
    — and keeps a local copy so the next read costs nothing."""
    store = FakeStore()
    key = sequence_key(10.0, 0.0, "D6", 0.3)
    Cache(tmp_path / "first", store=store).put_manifest(key, {"target": "x", "frames": []})

    second = Cache(tmp_path / "second", store=store)

    assert second.manifest(key) == {"target": "x", "frames": []}
    assert (second.sequence_dir(key) / "manifest.json").exists()


def test_frames_read_through_the_store(tmp_path):
    store = FakeStore()
    key = frame_key("obs", 10.0, 0.0, 0.3)
    Cache(tmp_path / "a", store=store).put_frame(key, b"RIFF-webp")

    assert Cache(tmp_path / "b", store=store).frame(key) == b"RIFF-webp"


def test_ensure_local_downloads_a_file_once(tmp_path):
    store = FakeStore()
    key = cube_key(10.0, 0.0, 0.3)
    builder = Cache(tmp_path / "a", store=store)
    path = builder.cube_file(key, "plane_003.webp")
    path.parent.mkdir(parents=True)
    path.write_bytes(b"RIFF")
    builder.publish_cube(key)

    other = Cache(tmp_path / "b", store=store)
    target = other.cube_file(key, "plane_003.webp")
    before = len(store.gets)

    other.ensure_local(target)
    other.ensure_local(target)

    assert target.read_bytes() == b"RIFF"
    assert len(store.gets) - before == 1


def test_a_publish_failure_does_not_break_the_local_write(tmp_path):
    """A bucket outage costs durability, not the request: the file is already on disk."""

    class Broken(FakeStore):
        def put_bytes(self, name, data):
            raise RuntimeError("bucket down")

    cache = Cache(tmp_path, store=Broken())
    key = sequence_key(10.0, 0.0, "D6", 0.3)

    cache.put_manifest(key, {"frames": []})

    assert cache.manifest(key) == {"frames": []}


def test_progress_uploads_are_throttled_but_a_final_state_goes_at_once(tmp_path):
    store = FakeStore()
    cache = Cache(tmp_path, store=store)
    key = cube_key(10.0, 0.0, 0.3)
    uploads = lambda: [name for name in store.puts if name.endswith("progress.json")]  # noqa: E731

    cache.put_progress(key, {"state": "building", "stage": "downloading_tile"})
    cache.put_progress(key, {"state": "building", "stage": "rendering_planes"})

    assert len(uploads()) == 1

    cache.put_progress(key, {"state": "done"})

    # The final state must be durable immediately: a restarted instance reading a two-second-old
    # "building" would keep a dead job on the queue.
    assert len(uploads()) == 2
    assert cache.progress(key)["state"] == "done"
