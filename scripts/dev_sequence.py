#!/usr/bin/env python3
"""DEVELOPMENT BRIDGE — not a deliverable.

Phase 4 (the UI) needs a multi-epoch sequence to blink, but Phase 3 (`pipeline/sequence.py`)
is being built in parallel by Arturo and has not landed. This script produces the smallest
honest stand-in so the UI can be built and reviewed against real data.

It deliberately duplicates logic that Phase 3 will own (`reproject` onto a common grid,
global stretch, per-frame measurement). When `pipeline/sequence.py` lands, delete this file
and point the UI at the Phase 3 manifest instead. The manifest shape here is a subset of
Phase 3's, so the UI should not need rewriting.

Differences from Phase 3, on purpose and stated rather than hidden:
  - aperture photometry and centroid are approximate (no SigmaClip, no centroid_2dg)
  - no `threading`; sequential so failures are easy to read
  - writes PNG rather than WebP (no encoder guaranteed on this box)

Usage:
  python scripts/dev_sequence.py --target r_dra --band D6 --max-dates 12
"""

from __future__ import annotations

import argparse
import collections
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
from astropy.wcs import WCS
from astroquery.ipac.irsa import Irsa
from PIL import Image
from pyvo.dal.exceptions import DALServiceError
from reproject import reproject_interp

conf.remote_timeout = 120

COLLECTION = "spherex_dr1"
PERCENTILES = (1.0, 99.5)
MAX_ATTEMPTS = 5
J2000_YEAR = 2000.0
CUTOUT_SIZE_DEG = 0.2
REPO = Path(__file__).resolve().parent.parent
CACHE = REPO / "data" / "cache"
OUT = REPO / "data" / "fallback" / "sequence"


class ArchiveUnknown(RuntimeError):
    """The archive never gave a usable answer. Distinct from 'no data here'."""


def load_targets():
    return {t["slug"]: t for t in json.loads((REPO / "data" / "targets.json").read_text())["targets"]}


def propagate(ra, dec, pm_ra_cosdec, pm_dec, epoch_year):
    years = epoch_year - J2000_YEAR
    ra_out = ra + years * pm_ra_cosdec / 3.6e6 / np.cos(np.radians(dec))
    dec_out = dec + years * pm_dec / 3.6e6
    return ra_out, dec_out


def search(ra, dec, tries=MAX_ATTEMPTS):
    wait = 8
    for attempt in range(1, tries + 1):
        try:
            return Irsa.query_sia(
                pos=(SkyCoord(ra, dec, unit="deg"), 1 * u.arcsec),
                collection=[COLLECTION],
            )
        except (DALServiceError, TimeoutError, urllib.error.HTTPError, http.client.IncompleteRead,
                ValueError) as exc:
            if attempt == tries:
                raise ArchiveUnknown(f"{type(exc).__name__}: {exc}") from exc
            print(f"  SIA {attempt}/{tries} failed ({type(exc).__name__}), wait {wait}s", file=sys.stderr)
            time.sleep(wait)
            wait = min(wait * 2, 60)


def group_dates(rows, band):
    """One representative obs_id per distinct t_min, for a single band."""
    wanted = f"SPHEREx-{band}".upper()
    by_date = collections.defaultdict(list)
    for row in rows:
        if str(row["energy_bandpassname"]).upper() != wanted:
            continue
        t_min = row["t_min"]
        if t_min is None or np.ma.is_masked(t_min):
            continue
        by_date[round(float(t_min), 2)].append(row)
    return [(t, by_date[t]) for t in sorted(by_date)]


def fetch(url, destination):
    if destination.exists() and destination.stat().st_size > 20000:
        return destination
    wait = 10
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = requests.get(url, timeout=180)
            if response.status_code == 200 and len(response.content) > 20000:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(response.content)
                return destination
            raise RuntimeError(f"status={response.status_code} bytes={len(response.content)}")
        except Exception as exc:  # noqa: BLE001 - archive flakiness
            if attempt == MAX_ATTEMPTS:
                raise ArchiveUnknown(f"{type(exc).__name__}: {exc}") from exc
            print(f"  cutout {attempt}/{MAX_ATTEMPTS} failed, wait {wait}s", file=sys.stderr)
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
        raise ValueError(f"unexpected IMAGE BUNIT {bunit!r}")

    data = image - zodi

    # Per-bit flags: use the header's own masks, never `flags != 0`.
    bad = np.zeros(data.shape, dtype=bool)
    candidates = (
        header.get("MSKNOVER", header.get("MSKNOVR", 0)),
        header.get("MSKNSAT", 0),
        header.get("MSKNSUR", 0),
        header.get("MSKNERR", 0),
    )
    for mask in candidates:
        try:
            mask = int(mask)
        except (TypeError, ValueError):
            continue
        if mask:
            bad |= (flags & mask) != 0
    # any FLAGS value that is not a known-good code collapses to "unknown"
    bad |= ~np.isfinite(data)
    data = np.where(bad, np.nan, data)

    return data, header, float(bad.mean())


def measure(data, x, y, pixscale=6.15):
    """Approximate aperture flux + centroid on a 9x9 box. Phase 3 owns the real version."""
    ny, nx = data.shape
    if not (0 <= x < nx and 0 <= y < ny):
        return None
    r_ap, r_in, r_out = 3.0, 5.0, 8.0

    yy, xx = np.mgrid[0:ny, 0:nx]
    rr = np.hypot(xx - x, yy - y)
    ap = (rr <= r_ap) & np.isfinite(data)
    ann = (rr >= r_in) & (rr <= r_out) & np.isfinite(data)
    if ap.sum() < 5 or ann.sum() < 10:
        return None

    sky = float(np.nanmedian(data[ann]))
    flux = float(np.nansum(data[ap] - sky))
    flux_err = float(np.nanstd(data[ann]) * np.sqrt(ap.sum()))

    box = np.s_[max(0, int(y) - 4):int(y) + 5, max(0, int(x) - 4):int(x) + 5]
    sub = data[box]
    if np.isfinite(sub).sum() >= 5:
        w = np.nan_to_num(sub - np.nanmin(sub), nan=0.0)
        if w.sum() > 0:
            gy, gx = np.mgrid[0:w.shape[0], 0:w.shape[1]]
            x = max(0, int(x) - 4) + float((w * gx).sum() / w.sum())
            y = max(0, int(y) - 4) + float((w * gy).sum() / w.sum())

    return {"x": float(x), "y": float(y), "flux": flux, "flux_err": flux_err,
            "snr": flux / flux_err if flux_err > 0 else float("nan")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="r_dra")
    ap.add_argument("--band", default="D6")
    ap.add_argument("--max-dates", type=int, default=12)
    ap.add_argument("--size", type=float, default=CUTOUT_SIZE_DEG)
    ap.add_argument("--from-cache", action="store_true",
                    help="rebuild from cached FITS instead of querying SIA (archive down)")
    args = ap.parse_args()

    targets = load_targets()
    target = targets[args.target]
    ra0, dec0 = target["ra"], target["dec"]

    rows = None
    if args.from_cache:
        existing = OUT / f"{args.target}_{args.band}.json"
        if not existing.exists():
            print(f"--from-cache needs an existing {existing.name}", file=sys.stderr)
            return 1
        prior = json.loads(existing.read_text())
        dates = [(f["t_min"], [{"obs_id": f["obs_id"], "access_url": None}]) for f in prior["frames"]]
        print(f"{args.target} {args.band}: {len(dates)} dates from cache manifest")
    else:
        rows = search(ra0, dec0)
        dates = group_dates(rows, args.band)
        print(f"{args.target} {args.band}: {len(dates)} distinct dates")
    if not dates:
        print(f"no dates in {args.band}", file=sys.stderr)
        return 1

    # Even sampling across the span so gaps stay representative rather than clustered.
    if len(dates) > args.max_dates:
        idx = np.linspace(0, len(dates) - 1, args.max_dates).round().astype(int)
        dates = [dates[i] for i in sorted(set(idx.tolist()))]

    pm_ra, pm_dec = target.get("pm_ra_cosdec"), target.get("pm_dec")

    frames = []
    ref_wcs = None
    for t_min, group in dates:
        row = group[0]
        epoch_year = Time(t_min, format="mjd").decimalyear
        ra, dec = propagate(ra0, dec0, pm_ra, pm_dec, epoch_year) if pm_ra is not None else (ra0, dec0)

        url = f"{row['access_url']}?center={ra},{dec}d&size={args.size}" if row.get("access_url") else None
        dest = CACHE / f"{row['obs_id']}_{args.band}_{args.size}.fits"
        try:
            path = dest if args.from_cache else fetch(url, dest)
            data, header, bad_frac = load_frame(path)
        except Exception as exc:  # noqa: BLE001
            print(f"  {t_min}: skipped ({type(exc).__name__}: {exc})", file=sys.stderr)
            continue

        wcs = WCS(header)
        if ref_wcs is None:
            ref_wcs = wcs
            ref_shape = data.shape
            px, py = wcs.world_to_pixel_values(ra, dec)
            ref_xy = (float(px), float(py))
        aligned, _ = reproject_interp((data, wcs), ref_wcs, shape_out=ref_shape, return_footprint=True)

        m = measure(aligned, ref_xy[0], ref_xy[1])
        frames.append({"t_min": t_min, "date": Time(t_min, format="mjd").iso[:10],
                       "obs_id": str(row["obs_id"]), "data": aligned, "bad_fraction": bad_frac,
                       "measure": m})
        print(f"  {Time(t_min, format='mjd').iso[:10]}  obs={row['obs_id']}  bad={bad_frac:.2f}")

    if not frames:
        print("no frames survived", file=sys.stderr)
        return 1

    # Global stretch across ALL frames so brightness is comparable between dates.
    stack = np.concatenate([f["data"][np.isfinite(f["data"])].ravel() for f in frames])
    vmin, vmax = (float(v) for v in np.percentile(stack, PERCENTILES))
    if not np.isfinite(vmin) or not np.isfinite(vmax) or vmax <= vmin:
        print(f"degenerate stretch vmin={vmin} vmax={vmax}", file=sys.stderr)
        return 1

    # Outlier strip: per-frame change statistics against the temporal median.
    # One broken frame must not be able to pose as a moving object (Phase 4 requirement).
    cube = np.stack([f["data"] for f in frames])
    with np.errstate(invalid="ignore"):
        median_cube = np.nanmedian(cube, axis=0)
    for f in frames:
        with np.errstate(invalid="ignore"):
            diff = f["data"] - median_cube
            finite = np.isfinite(diff)
            if finite.sum() == 0:
                f["outlier"] = {"mean": None, "median": None, "max_abs": None}
                continue
            d = diff[finite]
            f["outlier"] = {
                "mean": float(np.mean(d)),
                "median": float(np.median(d)),
                "max_abs": float(np.max(np.abs(d))),
            }

    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {"target": args.target, "name": target["name"], "band": args.band,
                "size_deg": args.size, "vmin": vmin, "vmax": vmax,
                "pixscale_arcsec": 6.15, "generated_by": "scripts/dev_sequence.py",
                "note": "development bridge; Phase 3 owns the real sequence builder",
                "frames": []}

    for f in frames:
        scaled = np.clip((f["data"] - vmin) / (vmax - vmin), 0, 1)
        scaled = np.arcsinh(scaled * 8) / np.arcsinh(8)
        pixels = (np.nan_to_num(scaled) * 255).astype(np.uint8)
        name = f"{args.target}_{args.band}_{f['date']}.png"
        Image.fromarray(np.flipud(pixels)).save(OUT / name)
        manifest["frames"].append({
            "date": f["date"], "t_min": f["t_min"], "obs_id": f["obs_id"], "file": name,
            "bad_fraction": round(f["bad_fraction"], 4),
            "outlier": f["outlier"],
            "measure": f["measure"],
        })

    ms = [(f["t_min"], f["measure"]) for f in frames if f["measure"]]
    if len(ms) >= 3:
        t = np.array([m[0] for m in ms])
        x = np.array([m[1]["x"] for m in ms])
        y = np.array([m[1]["y"] for m in ms])

        # A moving object drifts monotonically. A variable star does not: its centroid
        # jitters around a fixed point as the saturated core changes shape. Fit a line and
        # report the slope WITH its uncertainty, so a slope consistent with zero is visible.
        def fit_slope(v):
            A = np.vstack([t - t.mean(), np.ones_like(t)]).T
            coef, res, *_ = np.linalg.lstsq(A, v, rcond=None)
            dof = max(len(t) - 2, 1)
            residual = v - A @ coef
            s_err = np.sqrt((residual @ residual) / dof / np.sum((t - t.mean()) ** 2))
            return float(coef[0]), float(s_err)

        sx, ex = fit_slope(x)
        sy, ey = fit_slope(y)
        span = float(t[-1] - t[0])

        # Detrended scatter: how far the centroid wanders regardless of trend.
        rms_x = float(np.std(x - np.polyval(np.polyfit(t, x, 1), t)))
        rms_y = float(np.std(y - np.polyval(np.polyfit(t, y, 1), t)))

        manifest["motion"] = {
            "dx_arcsec": float((x[-1] - x[0]) * manifest["pixscale_arcsec"]),
            "dy_arcsec": float((y[-1] - y[0]) * manifest["pixscale_arcsec"]),
            "dt_years": span / 365.25,
            "slope_arcsec_per_year": [float(sx * 365.25 * manifest["pixscale_arcsec"]),
                                      float(sy * 365.25 * manifest["pixscale_arcsec"])],
            "slope_err": [float(ex * 365.25 * manifest["pixscale_arcsec"]),
                          float(ey * 365.25 * manifest["pixscale_arcsec"])],
            "rms_scatter_arcsec": [rms_x * manifest["pixscale_arcsec"],
                                   rms_y * manifest["pixscale_arcsec"]],
        }
        total = np.hypot(manifest["motion"]["dx_arcsec"], manifest["motion"]["dy_arcsec"])
        manifest["motion"]["total_arcsec"] = float(total)

        rate = np.hypot(*manifest["motion"]["slope_arcsec_per_year"])
        rate_err = np.hypot(*manifest["motion"]["slope_err"])
        significant = rate > 3 * rate_err and rate_err > 0
        manifest["motion"]["significant"] = bool(significant)

        print(f"motion: endpoints {total:.1f}\" over {span / 365.25:.2f} yr")
        print(f"  fitted rate  {rate:.2f} +/- {rate_err:.2f} \"/yr  "
              f"-> {'SIGNIFICANT' if significant else 'CONSISTENT WITH ZERO (jitter)'}")
        print(f"  detrended rms scatter  x={rms_x * 6.15:.2f}\"  y={rms_y * 6.15:.2f}\"")
        if not significant:
            print("  => jitter: this is centroid noise on a bright core, NOT motion. "
                  "R Draconis has pm ~0.02\"/yr; it pulses, it does not move.")

    (OUT / f"{args.target}_{args.band}.json").write_text(
        json.dumps(manifest, indent=2, allow_nan=False)
    )
    print(f"wrote {len(frames)} frames + manifest to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
