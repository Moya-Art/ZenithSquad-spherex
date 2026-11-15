#!/usr/bin/env python3
"""One preview PNG per target: SIA query -> cutout -> IMAGE - ZODI -> percentile stretch.

Phase 1 of the build plan. Nothing here is imported by later phases except by copying:
the script only proves that each target is visible in the band we picked.
"""

from __future__ import annotations

import argparse
import http.client
import json
import sys
import time
import urllib.error
from pathlib import Path

import numpy as np
import requests
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.time import Time
from astropy.utils.data import conf
from astroquery.ipac.irsa import Irsa
from PIL import Image
from pyvo.dal.exceptions import DALServiceError

conf.remote_timeout = 120

COLLECTION = "spherex_dr1"
SEARCH_RADIUS = 1 * u.arcsec
PERCENTILES = (1.0, 99.5)
MAX_ATTEMPTS = 5
J2000_YEAR = 2000.0

EXIT_UNKNOWN = 2
EXIT_NO_ROWS = 3


class ArchiveUnknown(RuntimeError):
    """The archive never produced a usable answer; distinct from a sky region with no data."""


def load_targets(path):
    return json.loads(Path(path).read_text())["targets"]


def sia_name(band):
    return f"SPHEREx-{band}"


def propagate(ra, dec, pm_ra_cosdec, pm_dec, epoch_year):
    """Move a J2000 position to the exposure epoch with constant proper motion.

    First order is enough here: the largest motion among these targets is 0.077 deg
    (Barnard's Star), where the neglected second-order term is well under an arcsecond.
    """
    years = epoch_year - J2000_YEAR
    ra_out = ra + years * pm_ra_cosdec / 3.6e6 / np.cos(np.radians(dec))
    dec_out = dec + years * pm_dec / 3.6e6
    return ra_out, dec_out


def search_rows(ra, dec, collection=COLLECTION):
    coord = SkyCoord(ra, dec, unit="deg")
    wait = 10
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return Irsa.query_sia(pos=(coord, SEARCH_RADIUS), collection=[collection])
        except (
            DALServiceError,
            TimeoutError,
            urllib.error.HTTPError,
            http.client.IncompleteRead,
        ) as error:
            if attempt == MAX_ATTEMPTS:
                raise ArchiveUnknown(f"{type(error).__name__}: {error}") from error
            print(
                f"  SIA attempt {attempt}/{MAX_ATTEMPTS} failed "
                f"({type(error).__name__}), retrying in {wait}s",
                file=sys.stderr,
            )
            time.sleep(wait)
            wait *= 2


def pick_row(rows, band, obs_id=None):
    if obs_id is not None:
        for row in rows:
            if str(row["obs_id"]) == obs_id:
                return row
        raise LookupError(f"obs_id {obs_id} is not among the {len(rows)} rows returned")

    wanted = sia_name(band)
    selected = [row for row in rows if str(row["energy_bandpassname"]).upper() == wanted.upper()]
    if not selected:
        bands = sorted({str(row["energy_bandpassname"]) for row in rows})
        raise LookupError(f"no rows in {band} here; bands returned: {bands}")

    def observation_time(row):
        for column in ("t_min", "obs_release_date"):
            if column in row.colnames:
                return str(row[column])
        return ""

    return max(selected, key=observation_time)


def cutout_url(access_url, ra, dec, size_deg):
    return f"{access_url}?center={ra},{dec}d&size={size_deg}"


def fetch_cutout(url, destination):
    if destination.exists():
        return destination
    wait = 10
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = requests.get(url, timeout=180)
            response.raise_for_status()
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(response.content)
            return destination
        except requests.RequestException as error:
            if attempt == MAX_ATTEMPTS:
                raise ArchiveUnknown(f"cutout download failed: {error}") from error
            print(
                f"  cutout attempt {attempt}/{MAX_ATTEMPTS} failed ({error}), "
                f"retrying in {wait}s",
                file=sys.stderr,
            )
            time.sleep(wait)
            wait *= 2


def load_frame(path):
    with fits.open(path, memmap=False) as hdul:
        image = hdul["IMAGE"].data.astype(float)
        zodi = hdul["ZODI"].data.astype(float)
        flags = hdul["FLAGS"].data
        header = hdul["IMAGE"].header.copy()

    bunit = str(header.get("BUNIT", "")).strip()
    if bunit.replace(" ", "").lower() != "mjy/sr":
        raise ValueError(f"unexpected IMAGE BUNIT {bunit!r}; this script assumes MJy/sr")

    return image - zodi, header, flags


def stretch(data):
    finite = data[np.isfinite(data)]
    if finite.size == 0:
        raise ValueError("no finite pixels in this cutout")
    vmin, vmax = np.percentile(finite, PERCENTILES)
    if not np.isfinite(vmin) or not np.isfinite(vmax) or vmax <= vmin:
        raise ValueError(f"cannot stretch: vmin={vmin} vmax={vmax}")
    scaled = (data - vmin) / (vmax - vmin)
    scaled = np.clip(np.nan_to_num(scaled, nan=0.0), 0.0, 1.0)
    return (scaled * 255).astype(np.uint8), float(vmin), float(vmax)


def save_png(pixels, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    # FITS row 0 is the bottom of the image; flip so north is up.
    Image.fromarray(np.flipud(pixels)).save(path)


def observation_year(row):
    for column in ("t_min", "t_max"):
        if column in row.colnames:
            try:
                return Time(float(row[column]), format="mjd").decimalyear
            except (TypeError, ValueError):
                continue
    return None


def preview_target(target, band, size_deg, obs_id, out_dir, cache_dir):
    slug = target["slug"]
    rows = search_rows(target["ra"], target["dec"])
    print(f"{slug}: {len(rows)} rows in {COLLECTION}")
    row = pick_row(rows, band, obs_id=obs_id)

    ra, dec = target["ra"], target["dec"]
    epoch_year = observation_year(row)
    pm_ra, pm_dec = target.get("pm_ra_cosdec"), target.get("pm_dec")
    if pm_ra is not None and pm_dec is not None and epoch_year is not None:
        ra, dec = propagate(ra, dec, pm_ra, pm_dec, epoch_year)
        moved = SkyCoord(target["ra"], target["dec"], unit="deg").separation(
            SkyCoord(ra, dec, unit="deg")
        )
        epoch_note = f"epoch={epoch_year:.2f} pm_move={moved.arcsec:.1f}\""
    else:
        epoch_note = f"epoch={epoch_year} NO PROPER MOTION - centred on J2000"

    url = cutout_url(str(row["access_url"]), ra, dec, size_deg)
    destination = cache_dir / f"{row['obs_id']}_{band}_{size_deg}_{ra:.4f}_{dec:.4f}.fits"
    path = fetch_cutout(url, destination)

    data, header, flags = load_frame(path)
    pixels, vmin, vmax = stretch(data)
    out_path = out_dir / f"{slug}_{band}.png"
    save_png(pixels, out_path)

    finite = np.isfinite(data)
    print(
        f"{slug}: obs_id={row['obs_id']} date={header.get('DATE')} "
        f"detector={header.get('DETECTOR')} shape={data.shape} "
        f"bunit={header.get('BUNIT')} vmin={vmin:.3g} vmax={vmax:.3g} "
        f"nan_frac={1 - finite.mean():.3f} "
        f"flagged_frac={(flags != 0).mean():.3f} {epoch_note} -> {out_path}"
    )
    return out_path



def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", action="append", metavar="SLUG", help="repeatable; default all")
    parser.add_argument("--band", help="override the band from targets.json, e.g. D2")
    parser.add_argument("--size", type=float, default=0.3, help="cutout size in degrees")
    parser.add_argument("--obs-id", help="preview this exposure instead of the most recent one")
    parser.add_argument("--targets", default="data/targets.json")
    parser.add_argument("--out", default="data/fallback/preview")
    parser.add_argument("--cache", default="data/cache")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    targets = load_targets(args.targets)
    if args.target:
        wanted = set(args.target)
        targets = [target for target in targets if target["slug"] in wanted]
        missing = wanted - {target["slug"] for target in targets}
        if missing:
            print(f"unknown target slug(s): {sorted(missing)}", file=sys.stderr)
            return EXIT_NO_ROWS

    out_dir = Path(args.out)
    cache_dir = Path(args.cache)
    failures = {}

    for target in targets:
        band = args.band or target["band"]
        try:
            preview_target(target, band, args.size, args.obs_id, out_dir, cache_dir)
        except ArchiveUnknown as error:
            print(f"{target['slug']}: UNKNOWN from archive: {error}", file=sys.stderr)
            failures[target["slug"]] = EXIT_UNKNOWN
        except LookupError as error:
            print(f"{target['slug']}: {error}", file=sys.stderr)
            failures[target["slug"]] = EXIT_NO_ROWS
        except ValueError as error:
            print(f"{target['slug']}: {error}", file=sys.stderr)
            failures[target["slug"]] = EXIT_UNKNOWN

    if failures:
        print(f"failed targets: {failures}", file=sys.stderr)
        return EXIT_UNKNOWN if EXIT_UNKNOWN in failures.values() else EXIT_NO_ROWS
    return 0


if __name__ == "__main__":
    sys.exit(main())
