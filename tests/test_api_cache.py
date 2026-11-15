"""Cache keys and hit/miss verdicts. No network, no build — the filesystem is the subject."""

import json

from api.app.cache import Cache, frame_key, sequence_key


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
