"""The object store: naming, missing objects, and a failure that must not become an exception.

Nothing here touches the network. `GcsStore` is exercised against a fake client implementing the three
methods it uses, which is enough to pin the behaviour that matters: a missing object is `None`, an
upload failure is counted and logged rather than raised, and `ping` reports reachability without
turning a permissions error into a crash.
"""

from google.api_core.exceptions import Forbidden, NotFound

from api.app.store import GcsStore, LocalStore, default_store


class _Blob:
    def __init__(self, bucket, name):
        self.bucket = bucket
        self.name = name

    def download_as_bytes(self):
        if self.name in self.bucket.fail_on:
            raise PermissionError("denied")
        if self.name not in self.bucket.objects:
            raise NotFound(self.name)
        return self.bucket.objects[self.name]

    def upload_from_string(self, data):
        if self.name in self.bucket.fail_on:
            raise PermissionError("denied")
        self.bucket.objects[self.name] = data


class _Bucket:
    def __init__(self, name):
        self.name = name
        self.objects = {}
        self.fail_on = set()

    def blob(self, name):
        return _Blob(self, name)


class _Client:
    def __init__(self):
        self.buckets = {}
        self.listing_fails = False
        self.listings = 0

    def bucket(self, name):
        return self.buckets.setdefault(name, _Bucket(name))

    def list_blobs(self, bucket_name, prefix="", max_results=None):
        self.listings += 1
        if self.listing_fails:
            raise Forbidden("no permission")
        bucket = self.bucket(bucket_name)
        for name in sorted(bucket.objects):
            if name.startswith(prefix):
                yield type("_Listed", (), {"name": name})()


def _store():
    client = _Client()
    return GcsStore("test-bucket", client=client), client.bucket("test-bucket")


# --- the default -------------------------------------------------------------------------------


def test_without_a_bucket_nothing_is_uploaded(monkeypatch):
    monkeypatch.delenv("GCS_BUCKET", raising=False)
    store = default_store()

    assert isinstance(store, LocalStore)
    assert store.get_bytes("seq/k/manifest.json") is None
    assert store.put_bytes("seq/k/manifest.json", b"{}") is None
    assert store.list_prefix("seq/") == []


def test_no_bucket_means_health_says_unknown_not_reachable(monkeypatch):
    monkeypatch.delenv("GCS_BUCKET", raising=False)

    # None, not True: nobody checked, and claiming reachability would be a lie in /health.
    assert default_store().ping() is None


def test_a_configured_bucket_is_used(monkeypatch):
    monkeypatch.setenv("GCS_BUCKET", "zenith-squad-2026-artifacts")
    store = default_store()

    assert isinstance(store, GcsStore)
    assert store.bucket_name == "zenith-squad-2026-artifacts"


# --- GCS ---------------------------------------------------------------------------------------


def test_objects_round_trip_by_name():
    store, bucket = _store()

    store.put_bytes("seq/abc/manifest.json", b'{"frames": []}')

    assert bucket.objects["seq/abc/manifest.json"] == b'{"frames": []}'
    assert store.get_bytes("seq/abc/manifest.json") == b'{"frames": []}'


def test_a_missing_object_is_none_not_an_error():
    store, _ = _store()

    assert store.get_bytes("cubes/nope/cube.json") is None


def test_listing_is_filtered_by_prefix():
    store, _ = _store()
    store.put_bytes("cubes/one/progress.json", b"{}")
    store.put_bytes("cubes/two/progress.json", b"{}")
    store.put_bytes("seq/three/manifest.json", b"{}")

    assert store.list_prefix("cubes/") == ["cubes/one/progress.json", "cubes/two/progress.json"]


def test_a_failed_upload_is_counted_and_not_raised():
    """The build already succeeded and its files are on local disk: a bucket hiccup must not turn a
    finished artifact into a failed request."""
    store, bucket = _store()
    bucket.fail_on.add("cubes/k/cube/plane_002.webp")

    uploaded = store.put_many([
        ("cubes/k/cube.json", b"{}"),
        ("cubes/k/cube/plane_002.webp", b"RIFF"),
    ])

    assert uploaded == 1
    assert "cubes/k/cube.json" in bucket.objects


def test_ping_reports_an_unreachable_bucket_as_false():
    client = _Client()
    client.listing_fails = True
    store = GcsStore("test-bucket", client=client)

    assert store.ping() is False


def test_ping_uses_a_listing_not_a_metadata_read():
    """`bucket.reload()` needs storage.buckets.get, which a bucket-scoped object role does not grant:
    it reported a working bucket as unreachable on the deployed service."""
    client = _Client()
    store = GcsStore("test-bucket", client=client)

    assert store.ping() is True
    assert client.listings == 1


def test_ping_is_cached_so_health_does_not_hammer_the_bucket():
    client = _Client()
    store = GcsStore("test-bucket", client=client)

    store.ping()
    store.ping()
    store.ping()

    assert client.listings == 1
