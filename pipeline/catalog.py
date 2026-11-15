"""SIA catalogue layer: query images around a coordinate, group them into epochs, summarise.

Standard library only — no astroquery, no FITS. BUILD_PLAN §2 fixes the query form and
§1.1 fixes the counting rules that `summarise` implements.

The response is parsed as VOTable, not CSV: IRSA's CSV output writes `s_region` (a POLYGON) with
unquoted commas, so splitting a CSV row by comma invents columns. VOTable is the native SIA
response and has no such ambiguity.

The one distinction this module exists to protect: an archive that does not answer
(`ArchiveUnknown`) is never the same thing as a sky region that has no data (zero rows).
"""

from __future__ import annotations

import http.client
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

SIA_ENDPOINT = "https://irsa.ipac.caltech.edu/SIA"

DEFAULT_RADII = (0.001,)
"""The search radius is part of the measurement, so it is fixed rather than adaptive.

Widening 0.001 deg to 0.01 deg on a failure was measured to change the answer — R Draconis goes
from 413 frames to 422, Epsilon Indi QR3 from 116 to 117 — which would make a timeline
irreproducible without saying so. A 502 now surfaces as UNKNOWN and the caller retries or passes
a wider `radii` deliberately.
"""

MAX_ATTEMPTS = 4
RETRY_WAIT_SECONDS = 10
REQUEST_TIMEOUT = 120

EPOCH_GAP_DAYS = 30

REQUIRED_COLUMNS = ("obs_id", "t_min", "energy_bandpassname")

MJD_EPOCH = date(1858, 11, 17)

CLIENT_ERROR_CODES = (400, 404)


class ArchiveUnknown(RuntimeError):
    """The archive never produced a usable answer, as opposed to returning no rows."""


class SchemaError(RuntimeError):
    """The response did not look like the SIA CSV this module expects."""


@dataclass(frozen=True)
class Frame:
    obs_id: str
    date: date
    mjd: float
    band: str


@dataclass(frozen=True)
class Epoch:
    start: date
    end: date
    n_dates: int
    n_frames: int


@dataclass(frozen=True)
class Summary:
    n_frames: int
    n_obs: int
    n_dates: int
    first: date | None
    last: date | None
    bands: dict[str, dict[str, int]]
    epochs: list[Epoch]
    gaps: list[int]
    radius_deg: float | None = None

    def counts(self) -> dict[str, object]:
        return {
            "frames": self.n_frames,
            "obs": self.n_obs,
            "dates": self.n_dates,
            "first": self.first.isoformat() if self.first else None,
            "last": self.last.isoformat() if self.last else None,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self.counts(),
            "radius_deg": self.radius_deg,
            "bands": self.bands,
            "epochs": [
                {
                    "start": epoch.start.isoformat(),
                    "end": epoch.end.isoformat(),
                    "dates": epoch.n_dates,
                    "frames": epoch.n_frames,
                }
                for epoch in self.epochs
            ],
            "gaps_days": self.gaps,
        }


def load_targets(path: str | Path = "data/targets.json") -> list[dict]:
    return json.loads(Path(path).read_text())["targets"]


def sia_url(ra: float, dec: float, collection: str, radius_deg: float) -> str:
    params = {
        "POS": f"CIRCLE {ra} {dec} {radius_deg}",
        "COLLECTION": collection,
        "RESPONSEFORMAT": "votable",
    }
    return f"{SIA_ENDPOINT}?{urllib.parse.urlencode(params, quote_via=urllib.parse.quote)}"


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _info_value(root: ElementTree.Element, name: str) -> str | None:
    for element in root.iter():
        if _local_name(element.tag) == "INFO" and element.get("name") == name:
            return element.get("value")
    return None


def parse_votable(text: str) -> list[dict[str, str]]:
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as error:
        raise SchemaError(f"response is not VOTable XML: {error}") from error

    status = _info_value(root, "QUERY_STATUS")
    if status is not None and status.upper() != "OK":
        message = _info_value(root, "QUERY_STATUS_MESSAGE") or ""
        raise SchemaError(f"SIA reported QUERY_STATUS={status} {message}".strip())
    if _info_value(root, "OVERFLOW") is not None:
        raise ArchiveUnknown(f"SIA truncated the result: {_info_value(root, 'OVERFLOW')}")

    fields = [
        element.get("name") for element in root.iter() if _local_name(element.tag) == "FIELD"
    ]
    if not fields:
        raise SchemaError("SIA response has no FIELD definitions")
    missing = [name for name in REQUIRED_COLUMNS if name not in fields]
    if missing:
        raise SchemaError(
            f"SIA response is missing column(s) {missing}; columns returned: {fields}"
        )

    rows = []
    index = 0
    for row_element in root.iter():
        if _local_name(row_element.tag) != "TR":
            continue
        index += 1
        cells = [cell for cell in row_element if _local_name(cell.tag) == "TD"]
        if len(cells) != len(fields):
            raise SchemaError(f"row {index} has {len(cells)} cells against {len(fields)} columns")
        rows.append({name: (cell.text or "") for name, cell in zip(fields, cells)})
    return rows


def fetch_rows_with_radius(
    ra: float,
    dec: float,
    collection: str,
    *,
    radii: tuple[float, ...] = DEFAULT_RADII,
    timeout: float = REQUEST_TIMEOUT,
    max_attempts: int = MAX_ATTEMPTS,
) -> tuple[list[dict[str, str]], float]:
    """Query one collection, widening the radius before giving up on the archive.

    Returns the rows and the radius that answered: the count depends on it, because a circle of
    0.001 deg and one of 0.01 deg are different queries (Epsilon Indi QR3 differs by one frame).
    """
    last_error: Exception | None = None

    for radius_deg in radii:
        url = sia_url(ra, dec, collection, radius_deg)
        wait = RETRY_WAIT_SECONDS
        for attempt in range(1, max_attempts + 1):
            try:
                with urllib.request.urlopen(url, timeout=timeout) as response:
                    return parse_votable(response.read().decode("utf-8", "replace")), radius_deg
            except urllib.error.HTTPError as error:
                if error.code in CLIENT_ERROR_CODES:
                    raise SchemaError(
                        f"SIA rejected the query for {collection} at radius {radius_deg} deg: "
                        f"HTTP {error.code}"
                    ) from error
                last_error = error
            except (
                urllib.error.URLError,
                TimeoutError,
                ConnectionError,
                http.client.HTTPException,
            ) as error:
                last_error = error

            if attempt < max_attempts:
                time.sleep(wait)
                wait *= 2

    raise ArchiveUnknown(
        f"{collection} at ra={ra} dec={dec}: {type(last_error).__name__}: {last_error}"
    )


def fetch_rows(
    ra: float,
    dec: float,
    collection: str,
    *,
    radii: tuple[float, ...] = DEFAULT_RADII,
    timeout: float = REQUEST_TIMEOUT,
    max_attempts: int = MAX_ATTEMPTS,
) -> list[dict[str, str]]:
    rows, _ = fetch_rows_with_radius(
        ra, dec, collection, radii=radii, timeout=timeout, max_attempts=max_attempts
    )
    return rows


def mjd_to_date(mjd: float) -> date:
    return MJD_EPOCH + timedelta(days=int(float(mjd)))


def band_label(raw: str) -> str:
    text = str(raw).strip()
    if "-" in text:
        head, tail = text.rsplit("-", 1)
        if head.upper().startswith("SPHEREX") and tail:
            return tail
    return text


def frames_from_rows(rows: list[dict[str, str]]) -> list[Frame]:
    frames = []
    for index, row in enumerate(rows, start=1):
        obs_id = str(row["obs_id"]).strip()
        if not obs_id:
            raise SchemaError(f"row {index} has an empty obs_id")
        try:
            mjd = float(row["t_min"])
        except (TypeError, ValueError) as error:
            raise SchemaError(f"row {index} has an unparseable t_min {row['t_min']!r}") from error
        frames.append(
            Frame(
                obs_id=obs_id,
                date=mjd_to_date(mjd),
                mjd=mjd,
                band=band_label(row["energy_bandpassname"]),
            )
        )
    return frames


def gaps_days(dates: list[date]) -> list[int]:
    return [(later - earlier).days for earlier, later in zip(dates, dates[1:])]


def group_epochs(frames: list[Frame], gap_days: int = EPOCH_GAP_DAYS) -> list[Epoch]:
    dates = sorted({frame.date for frame in frames})
    if not dates:
        return []

    frames_per_date: dict[date, int] = {}
    for frame in frames:
        frames_per_date[frame.date] = frames_per_date.get(frame.date, 0) + 1

    epochs: list[Epoch] = []
    start = previous = dates[0]
    n_dates, n_frames = 1, frames_per_date[dates[0]]

    for current in dates[1:]:
        if (current - previous).days > gap_days:
            epochs.append(Epoch(start=start, end=previous, n_dates=n_dates, n_frames=n_frames))
            start, n_dates, n_frames = current, 0, 0
        previous = current
        n_dates += 1
        n_frames += frames_per_date[current]

    epochs.append(Epoch(start=start, end=previous, n_dates=n_dates, n_frames=n_frames))
    return epochs


def summarise(
    frames: list[Frame],
    gap_days: int = EPOCH_GAP_DAYS,
    radius_deg: float | None = None,
) -> Summary:
    dates = sorted({frame.date for frame in frames})

    per_band: dict[str, dict[str, object]] = {}
    for frame in frames:
        entry = per_band.setdefault(frame.band, {"frames": 0, "dates": set()})
        entry["frames"] = int(entry["frames"]) + 1
        entry["dates"].add(frame.date)

    bands = {
        band: {"frames": int(entry["frames"]), "dates": len(entry["dates"])}
        for band, entry in sorted(per_band.items())
    }

    return Summary(
        n_frames=len(frames),
        n_obs=len({frame.obs_id for frame in frames}),
        n_dates=len(dates),
        first=dates[0] if dates else None,
        last=dates[-1] if dates else None,
        bands=bands,
        epochs=group_epochs(frames, gap_days=gap_days),
        gaps=gaps_days(dates),
        radius_deg=radius_deg,
    )


def search_epochs(
    ra: float,
    dec: float,
    collection: str,
    *,
    gap_days: int = EPOCH_GAP_DAYS,
    radii: tuple[float, ...] = DEFAULT_RADII,
) -> Summary:
    rows, radius_deg = fetch_rows_with_radius(ra, dec, collection, radii=radii)
    return summarise(frames_from_rows(rows), gap_days=gap_days, radius_deg=radius_deg)
