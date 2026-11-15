"""Build one target's time sequence: query, download, align, stretch, render, measure.

The sequence unit is the observing **date**, not the individual frame: one representative frame per
date, one WebP per date, one measurement per date. The build plan asks for "one WebP per date" and
"N frames sharing one vmin/vmax", which only reconcile if a sequence frame is a date — and Phase 12's
"one point per date" confirms it. `frames_available` records how many frames that date actually had.

Frames are measured on their native pixel grid and reprojected only for display, because
interpolation would smooth a PSF that is barely one pixel wide.
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import requests
from astropy.coordinates import SkyCoord
from astropy.time import Time
from reproject import reproject_interp

from pipeline import catalog
from pipeline.flags import (
    BAD_FLAG_NAMES,
    SATURATION_FLAG_NAMES,
    bad_mask,
    flag_bits,
    resolve_bits,
)
from pipeline.fits_io import load_cutout
from pipeline.measure import measure_frame, sky_offset
from pipeline.render import global_stretch, save_webp, to_uint8

DEFAULT_SIZE_DEG = 0.3
DEFAULT_WORKERS = 8
MAX_DOWNLOAD_ATTEMPTS = 4
RETRY_WAIT_SECONDS = 10
MAX_BAD_FRACTION = 0.05
CENTROID_ERROR_PX = 0.5
STAR_EXCLUDE_PX = 12.0

BAND_EDGES_UM = {
    "D1": (0.75, 1.09),
    "D2": (1.10, 1.62),
    "D3": (1.63, 2.41),
    "D4": (2.42, 3.82),
    "D5": (3.83, 4.41),
    "D6": (4.42, 5.00),
}


class DownloadFailed(RuntimeError):
    pass


@dataclass(frozen=True)
class FrameRef:
    obs_id: str
    date: date
    mjd: float
    band: str
    access_url: str
    frames_available: int = 1


@dataclass(frozen=True)
class SequenceRequest:
    slug: str
    collection: str = "spherex_dr1"
    band: str | None = None
    size_deg: float = DEFAULT_SIZE_DEG
    out_root: Path = Path("data/fallback")
    cache_dir: Path = Path("data/cache")
    workers: int = DEFAULT_WORKERS
    refresh: bool = False
    targets_path: str = "data/targets.json"


def pick_band(bands: dict[str, dict[str, int]]) -> str:
    """Most dates wins; then most frames; then the lower detector number.

    The build plan says "the band with the most dates, not D2 by reflex". Ties are real (R Draconis
    has D1 and D4 on 21 dates each), so the tie-break is written down instead of left to dict order.
    """
    if not bands:
        raise ValueError("no bands to choose from")
    return min(bands, key=lambda band: (-bands[band]["dates"], -bands[band]["frames"], band))


def frame_refs(rows: list[dict[str, str]], band: str) -> list[FrameRef]:
    refs = []
    for row, frame in zip(rows, catalog.frames_from_rows(rows)):
        if frame.band != band:
            continue
        refs.append(
            FrameRef(
                obs_id=frame.obs_id,
                date=frame.date,
                mjd=frame.mjd,
                band=frame.band,
                access_url=str(row["access_url"]),
            )
        )
    return sorted(refs, key=lambda ref: (ref.date, ref.mjd))


def one_frame_per_date(refs: list[FrameRef]) -> list[FrameRef]:
    counts: dict[date, int] = {}
    for ref in refs:
        counts[ref.date] = counts.get(ref.date, 0) + 1

    chosen: dict[date, FrameRef] = {}
    for ref in refs:
        chosen.setdefault(ref.date, ref)
    return [
        FrameRef(
            obs_id=chosen[day].obs_id,
            date=day,
            mjd=chosen[day].mjd,
            band=chosen[day].band,
            access_url=chosen[day].access_url,
            frames_available=counts[day],
        )
        for day in sorted(chosen)
    ]


def cutout_url(ref: FrameRef, ra: float, dec: float, size_deg: float) -> str:
    return f"{ref.access_url}?center={ra},{dec}d&size={size_deg}"


def download(url: str, destination: Path, refresh: bool = False) -> Path:
    if destination.exists() and not refresh:
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)

    wait = RETRY_WAIT_SECONDS
    last_error: Exception | None = None
    for attempt in range(1, MAX_DOWNLOAD_ATTEMPTS + 1):
        try:
            response = requests.get(url, timeout=180)
            response.raise_for_status()
            destination.write_bytes(response.content)
            return destination
        except Exception as error:
            last_error = error
            if attempt < MAX_DOWNLOAD_ATTEMPTS:
                time.sleep(wait)
                wait *= 2
    raise DownloadFailed(f"{url.split('?')[0]}: {type(last_error).__name__}: {last_error}")


def build_sequence(request: SequenceRequest, progress=None) -> dict:
    targets = catalog.load_targets(request.targets_path)
    target = next((item for item in targets if item["slug"] == request.slug), None)
    if target is None:
        raise KeyError(f"unknown target slug {request.slug!r}")

    rows = catalog.fetch_rows(target["ra"], target["dec"], request.collection)
    summary = catalog.summarise(catalog.frames_from_rows(rows))
    band = request.band or pick_band(summary.bands)
    if band not in summary.bands:
        raise ValueError(f"{request.slug} has no frames in {band}")

    refs = one_frame_per_date(frame_refs(rows, band))
    out_dir = Path(request.out_root) / request.slug

    def fetch(ref: FrameRef) -> tuple[FrameRef, Path, SkyCoord]:
        year = Time(ref.mjd, format="mjd").decimalyear
        ra, dec = catalog.propagate(
            target["ra"], target["dec"], target.get("pm_ra_cosdec"), target.get("pm_dec"), year
        )
        url = cutout_url(ref, ra, dec, request.size_deg)
        name = f"{ref.obs_id}_{band}_{request.size_deg}_{ra:.4f}_{dec:.4f}.fits"
        path = download(url, Path(request.cache_dir) / name, refresh=request.refresh)
        return ref, path, SkyCoord(ra, dec, unit="deg")

    with ThreadPoolExecutor(max_workers=request.workers) as pool:
        downloads = list(pool.map(fetch, refs))

    cutouts = []
    for ref, path, sky in downloads:
        cutout = load_cutout(path, sky=sky)
        cutouts.append((ref, cutout))
        if progress:
            progress(f"{ref.date} loaded {cutout.image.shape}")

    bits = flag_bits(cutouts[0][1].flag_header)
    bad_bits = resolve_bits(bits, BAD_FLAG_NAMES)
    saturation_bits = resolve_bits(bits, SATURATION_FLAG_NAMES)
    if not bad_bits:
        raise ValueError("the FLAGS header defines none of the expected flag names")

    measurements = []
    for ref, cutout in cutouts:
        measurement = measure_frame(cutout, cutout.target_xy, bad_bits, saturation_bits)
        measurements.append((ref, cutout, measurement))
        if progress:
            progress(
                f"{ref.date} measured x={measurement.x:.2f} y={measurement.y:.2f} "
                f"bad={measurement.bad_fraction:.3f} saturated={measurement.saturated}"
            )

    # Display copy: the archive stores NaN at the most saturated core pixels. Reprojecting NaN
    # smears it into a black hole in the middle of the star, so fill it with the frame's brightest
    # plausible value first. Measurements never see this array; they use the native image.
    display = []
    for _ref, cutout, _measurement in measurements:
        finite = np.isfinite(cutout.image)
        if finite.all():
            display.append(cutout.image)
        else:
            ceiling = float(np.nanpercentile(cutout.image, 99.9))
            display.append(np.where(finite, cutout.image, ceiling))

    reference = measurements[0][1].wcs
    shape = measurements[0][1].image.shape
    projected = []
    for (_ref, cutout, _measurement), frame in zip(measurements, display):
        array, _footprint = reproject_interp((frame, cutout.wcs), reference, shape_out=shape)
        projected.append(array)

    stack = np.array(projected)
    covered = np.all(np.isfinite(stack), axis=0)
    if not covered.any():
        raise ValueError("the frames do not overlap")
    rows_with = np.where(covered.any(axis=1))[0]
    cols_with = np.where(covered.any(axis=0))[0]
    crop = stack[:, rows_with[0]:rows_with[-1] + 1, cols_with[0]:cols_with[-1] + 1]

    # The saturated star must not set the scale: its halo reaches ~30 MJy/sr and would crush the
    # field (p99 ~2.8) into the bottom 9 % of the range. Exclude a disc around it from the
    # percentiles only; the star itself still renders, clipped to white.
    star_x = measurements[0][1].target_xy[0] - cols_with[0]
    star_y = measurements[0][1].target_xy[1] - rows_with[0]
    yy, xx = np.ogrid[: crop.shape[1], : crop.shape[2]]
    star_mask = np.hypot(xx - star_x, yy - star_y) <= STAR_EXCLUDE_PX

    vmin, vmax = global_stretch(list(crop), exclude=star_mask)
    webp_sizes = {}
    for (ref, _cutout, _measurement), frame in zip(measurements, crop):
        path = out_dir / f"{ref.date.isoformat()}.webp"
        webp_sizes[ref.date] = save_webp(to_uint8(frame, vmin, vmax), path)
    first_ref, first_cutout, first_measurement = measurements[0]
    last_ref, last_cutout, last_measurement = measurements[-1]
    dx, dy = sky_offset(
        first_cutout.wcs,
        (first_measurement.x, first_measurement.y),
        last_cutout.wcs,
        (last_measurement.x, last_measurement.y),
    )
    pixel_scale = float(
        np.sqrt(abs(np.linalg.det(first_cutout.wcs.pixel_scale_matrix))) * 3600
    )
    # The error on a position difference is whatever the centroids actually do — measured on the
    # sky, because cutouts sit on different pixel grids and raw pixel scatter mixes them. An
    # assumed 0.5 px would have called a 14 arcsec wander a detection; this does not.
    residuals_ra, residuals_dec = [], []
    for (_ref, cutout, measurement), (_r, _p, sky) in zip(measurements, downloads):
        measured_sky = cutout.wcs.pixel_to_world(measurement.x, measurement.y)
        delta_ra, delta_dec = sky.spherical_offsets_to(measured_sky)
        residuals_ra.append(delta_ra.to_value("arcsec"))
        residuals_dec.append(delta_dec.to_value("arcsec"))

    scatter_arcsec = float(
        np.sqrt(0.5 * (np.var(residuals_ra) + np.var(residuals_dec)))
    )
    scatter_arcsec = max(scatter_arcsec, 0.25 * pixel_scale)
    scatter_px = scatter_arcsec / pixel_scale
    position_error = float(np.sqrt(2) * scatter_arcsec)
    saturated_any = any(item[2].saturated for item in measurements)
    fallback_any = any(item[2].centroid_fallback for item in measurements)
    motion_reliable = not saturated_any and not fallback_any

    manifest = {
        "target": request.slug,
        "name": target.get("name", request.slug),
        "collection": request.collection,
        "band": band,
        "band_wavelength_um": BAND_EDGES_UM.get(band),
        "size_deg": request.size_deg,
        "pixel_scale_arcsec": round(pixel_scale, 3),
        "built": date.today().isoformat(),
        "vmin": vmin,
        "vmax": vmax,
        "n_frames": len(measurements),
        "n_bands_available": len(summary.bands),
        "motion_note": (
            "dx/dy is the measured offset between the first and last date, in arcseconds. A target "
            "whose proper motion is far below the 6.15 arcsec pixel reports a value consistent with "
            "zero, and that is the correct result rather than a failure. When the target core is "
            "saturated its centroid is biased by bloom, which drifts with the roll angle of each "
            "visit, so motion_reliable is false and dx/dy should not be read as a detection."
        ),
        "motion_reliable": motion_reliable,
        "frames": [
            {
                "date": ref.date.isoformat(),
                "t_min": ref.mjd,
                "obs_id": ref.obs_id,
                "webp": f"{ref.date.isoformat()}.webp",
                "bytes": webp_sizes[ref.date],
                "frames_available": ref.frames_available,
                "x": round(measurement.x, 3),
                "y": round(measurement.y, 3),
                "flux": round(measurement.flux, 4),
                "flux_err": round(measurement.flux_err, 4),
                "flux_is_lower_bound": measurement.saturated,
                "snr": None if measurement.snr is None else round(measurement.snr, 2),
                "bad_fraction": round(measurement.bad_fraction, 5),
                "aperture_flagged": measurement.aperture_flagged,
                "saturated": measurement.saturated,
                "centroid_from_prediction": measurement.centroid_fallback,
                "wavelength_um": (
                    None if measurement.wavelength_um is None
                    else round(measurement.wavelength_um, 3)
                ),
            }
            for ref, _cutout, measurement in measurements
        ],
        "dx_arcsec": round(dx, 3),
        "dy_arcsec": round(dy, 3),
        "dt_years": round((last_ref.mjd - first_ref.mjd) / 365.25, 4),
        "dx_err_arcsec": round(position_error, 3),
        "dy_err_arcsec": round(position_error, 3),
        "centroid_scatter_px": round(scatter_px, 3),
        "saturated_any": saturated_any,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "sequence.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest
