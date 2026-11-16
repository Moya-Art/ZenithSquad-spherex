"""Object storage behind the disk cache.

`Cache` answers "has this coordinate been built?" with files. On Cloud Run that disk dies with the
instance, so the same question has to stay answerable after a restart. This module is the smallest
thing that makes it so: a name-to-bytes store, one backend for local development (which does nothing)
and one for a GCS bucket.

Object names are the local path relative to the cache root, so `Cache` needs no translation table:
`seq/<key>/manifest.json`, `cubes/<key>/cube/plane_007.webp`, `frames/<key>.webp`.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

_log = logging.getLogger(__name__)

# A health endpoint that lands every ten seconds must not become a bucket metadata request every ten
# seconds. The answer is allowed to be half a minute old.
PING_TTL_SECONDS = 30.0
UPLOAD_WORKERS = 8


class LocalStore:
    """The default: every object already lives on the disk `Cache` writes to, so there is nothing to do.

    `ping()` returns None rather than True: no bucket is configured, and `/health` says so instead of
    claiming a reachability nobody checked.
    """

    enabled = False

    def get_bytes(self, name: str) -> bytes | None:
        return None

    def put_bytes(self, name: str, data: bytes) -> None:
        return None

    def put_many(self, items: list[tuple[str, bytes]]) -> int:
        return 0

    def list_prefix(self, prefix: str) -> list[str]:
        return []

    def ping(self) -> bool | None:
        return None


class GcsStore:
    """A GCS bucket. Private: the browser never talks to it, the API reads it server-side."""

    enabled = True

    def __init__(self, bucket_name: str, client=None) -> None:
        self.bucket_name = bucket_name
        self._client = client
        self._bucket = None
        self._lock = threading.Lock()
        self._pinged_at = 0.0
        self._pinged: bool | None = None

    # -- plumbing --------------------------------------------------------------------------------

    def _get_bucket(self):
        # Imported here, not at module scope: importing the library costs time on every cold start and
        # only matters when a bucket is actually configured.
        if self._bucket is None:
            with self._lock:
                if self._bucket is None:
                    from google.cloud import storage

                    self._client = self._client or storage.Client()
                    self._bucket = self._client.bucket(self.bucket_name)
        return self._bucket

    # -- reads -----------------------------------------------------------------------------------

    def get_bytes(self, name: str) -> bytes | None:
        from google.api_core.exceptions import NotFound

        try:
            return self._get_bucket().blob(name).download_as_bytes()
        except NotFound:
            return None

    def list_prefix(self, prefix: str) -> list[str]:
        client = self._client or self._get_bucket().client
        return [blob.name for blob in client.list_blobs(self.bucket_name, prefix=prefix)]

    # -- writes ----------------------------------------------------------------------------------

    def put_bytes(self, name: str, data: bytes) -> None:
        self._get_bucket().blob(name).upload_from_string(data)

    def put_many(self, items: list[tuple[str, bytes]]) -> int:
        """Upload a freshly built artifact. A failure is logged, never raised.

        The build already succeeded and its files are on local disk; turning a bucket hiccup into a
        failed request would punish a visitor for a durability problem they cannot see. The cost of a
        lost upload is that the next instance rebuilds.
        """
        done = 0

        def upload(item: tuple[str, bytes]) -> bool:
            name, data = item
            try:
                self.put_bytes(name, data)
                return True
            except Exception as error:  # noqa: BLE001 - reported, not swallowed
                _log.warning("upload failed for %s: %s", name, error)
                return False

        with ThreadPoolExecutor(max_workers=UPLOAD_WORKERS) as pool:
            for ok in pool.map(upload, items):
                done += 1 if ok else 0
        return done

    # -- health ----------------------------------------------------------------------------------

    def ping(self) -> bool | None:
        now = time.monotonic()
        if self._pinged is not None and now - self._pinged_at < PING_TTL_SECONDS:
            return self._pinged
        try:
            # A listing, not a bucket metadata read. `bucket.reload()` needs `storage.buckets.get`,
            # which a bucket-scoped object role does not grant — it would report a perfectly working
            # bucket as unreachable. `storage.objects.list` is in the role the service actually has.
            client = self._client or self._get_bucket().client
            next(iter(client.list_blobs(self.bucket_name, max_results=1)), None)
            value = True
        except Exception as error:  # noqa: BLE001 - a claim about reachability, not a crash
            _log.warning("bucket %s not reachable: %s", self.bucket_name, error)
            value = False
        self._pinged, self._pinged_at = value, now
        return value


def default_store() -> LocalStore | GcsStore:
    """The bucket if `GCS_BUCKET` is set, otherwise nothing at all.

    This one branch is what keeps local development, the CLI and the test suite working without
    credentials: with the variable unset nothing is uploaded and nothing is downloaded.
    """
    bucket = os.environ.get("GCS_BUCKET", "").strip()
    return GcsStore(bucket) if bucket else LocalStore()
