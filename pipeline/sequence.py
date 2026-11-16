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
from pipeline.flags import bad_fraction as frame_bad_fraction
from pipeline.fits_io import load_cutout
from pipeline.measure import TargetOutsideFrame, measure_frame, sky_offset
from pipeline.render import global_stretch, save_webp, to_uint8_asinh

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


@dataclass(frozen=True)
class PositionSpec:
    """A point on the sky to build a sequence for, named target or raw coordinate.

    Proper motion is optional because a coordinate typed into the URL has none: the cutout is then
    centred on the position as given, which is the only honest thing to do, and the manifest says so.
    """

    ra: float
    dec: float
    label: str
    name: str
    pm_ra_cosdec: float | None = None
    pm_dec: float | None = None


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


def fit_motion(
    years: np.ndarray, offsets_ra: np.ndarray, offsets_dec: np.ndarray
) -> dict:
    """Least-squares rate in arcsec/year, with an error that comes from the residuals.

    The first-vs-last offset alone cannot tell real motion from a centroid that wanders; the fitted
    rate and its scatter can, which is what the UI needs in order to say either.
    """
    design = np.vstack([years - years.mean(), np.ones_like(years)]).T
    spread = float(np.sum((years - years.mean()) ** 2))

    def one_axis(values: np.ndarray) -> tuple[float, float, float]:
        slope, _intercept = np.linalg.lstsq(design, values, rcond=None)[0]
        residuals = values - design @ np.linalg.lstsq(design, values, rcond=None)[0]
        slope_err = float(np.sqrt(np.sum(residuals ** 2) / max(len(values) - 2, 1) / spread))
        return float(slope), slope_err, float(np.sqrt(np.mean(residuals ** 2)))

    slope_ra, err_ra, rms_ra = one_axis(offsets_ra)
    slope_dec, err_dec, rms_dec = one_axis(offsets_dec)
    total = float(np.hypot(offsets_ra[-1] - offsets_ra[0], offsets_dec[-1] - offsets_dec[0]))

    significant = (
        abs(slope_ra) > 3.0 * err_ra or abs(slope_dec) > 3.0 * err_dec
    ) and total > 1.5 * float(np.hypot(rms_ra, rms_dec))

    return {
        "dx_arcsec": float(offsets_ra[-1] - offsets_ra[0]),
        "dy_arcsec": float(offsets_dec[-1] - offsets_dec[0]),
        "dt_years": float(years[-1] - years[0]),
        "slope_arcsec_per_year": [slope_ra, slope_dec],
        "slope_err": [err_ra, err_dec],
        "rms_scatter_arcsec": [rms_ra, rms_dec],
        "total_arcsec": total,
        "significant": bool(significant),
    }


def outlier_stats(stack: np.ndarray, frame: np.ndarray) -> dict:
    """How different this frame is from the median of the others, in image units."""
    reference = np.nanmedian(stack, axis=0)
    difference = np.abs(frame - reference)
    if not np.isfinite(difference).any():
        return {"mean": None, "median": None, "max_abs": None}
    return {
        "mean": float(np.nanmean(difference)),
        "median": float(np.nanmedian(difference)),
        "max_abs": float(np.nanmax(difference)),
    }


def build_sequence(request: SequenceRequest, progress=None,
                   raw_paths: list[Path] | None = None) -> dict:
    """Build one named target's sequence, resolving its position from `targets.json`."""
    targets = catalog.load_targets(request.targets_path)
    target = next((item for item in targets if item["slug"] == request.slug), None)
    if target is None:
        raise KeyError(f"unknown target slug {request.slug!r}")

    position = PositionSpec(
        ra=target["ra"],
        dec=target["dec"],
        label=target["slug"],
        name=target.get("name", target["slug"]),
        pm_ra_cosdec=target.get("pm_ra_cosdec"),
        pm_dec=target.get("pm_dec"),
    )
    return build_from_position(
        position,
        collection=request.collection,
        band=request.band,
        size_deg=request.size_deg,
        out_root=request.out_root,
        cache_dir=request.cache_dir,
        workers=request.workers,
        refresh=request.refresh,
        progress=progress,
        raw_paths=raw_paths,
    )


def build_from_position(
    position: PositionSpec,
    *,
    collection: str = "spherex_dr1",
    band: str | None = None,
    size_deg: float = DEFAULT_SIZE_DEG,
    out_root: Path = Path("data/fallback"),
    cache_dir: Path = Path("data/cache"),
    workers: int = DEFAULT_WORKERS,
    refresh: bool = False,
    write_manifest: bool = True,
    progress=None,
    raw_paths: list[Path] | None = None,
) -> dict:
    """Build the time sequence for any position: named target or a coordinate typed by a visitor.

    `write_manifest=False` lets a caller hold the manifest without a second read (the API caches it
    under its own key); the WebPs are always written under `out_root` because that is what the
    manifest's `file` fields point at.

    `raw_paths` is where the cutouts this build actually used are reported, so a caller can delete
    them once the WebPs exist. It is filled in, not returned: the builder has no business deciding
    whether its ingredients are still wanted, and a glob would delete another build's files.
    """
    rows = catalog.fetch_rows(position.ra, position.dec, collection)
    summary = catalog.summarise(catalog.frames_from_rows(rows))
    band = band or pick_band(summary.bands)
    if band not in summary.bands:
        raise ValueError(f"{position.label} has no frames in {band}")

    refs = one_frame_per_date(frame_refs(rows, band))
    # Layout follows web/src/data.ts, which Phase 4 already shipped: one JSON per target+band in a
    # flat directory, frame files prefixed so five targets cannot collide. BUILD_PLAN §5 says
    # data/fallback/{target}/; that is now a plan change, not a code detail.
    out_dir = Path(out_root) / "sequence"
    stem = f"{position.label}_{band}"

    def fetch(ref: FrameRef) -> tuple[FrameRef, Path, SkyCoord]:
        year = Time(ref.mjd, format="mjd").decimalyear
        ra, dec = catalog.propagate(
            position.ra,
            position.dec,
            position.pm_ra_cosdec,
            position.pm_dec,
            year,
        )
        url = cutout_url(ref, ra, dec, size_deg)
        name = f"{ref.obs_id}_{band}_{size_deg}_{ra:.4f}_{dec:.4f}.fits"
        path = download(url, Path(cache_dir) / name, refresh=refresh)
        return ref, path, SkyCoord(ra, dec, unit="deg")

    with ThreadPoolExecutor(max_workers=workers) as pool:
        downloads = list(pool.map(fetch, refs))

    if raw_paths is not None:
        raw_paths.extend(path for _ref, path, _sky in downloads)

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
    measure_skipped: dict[str, str] = {}
    for ref, cutout in cutouts:
        try:
            measurement = measure_frame(cutout, cutout.target_xy, bad_bits, saturation_bits)
        except TargetOutsideFrame as error:
            # A frame with no measurement is a fact about that frame, not a reason to lose the
            # sequence: the blink still has the image, and the manifest records why it is unmeasured.
            measure_skipped[ref.obs_id] = str(error)
            measurements.append((ref, cutout, None))
            if progress:
                progress(f"{ref.date} not measured: {error}")
            continue
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
        name = f"{stem}_{ref.date.isoformat()}.webp"
        webp_sizes[ref.date] = save_webp(to_uint8_asinh(frame, vmin, vmax), out_dir / name)

    pixel_scale = float(
        np.sqrt(abs(np.linalg.det(measurements[0][1].wcs.pixel_scale_matrix))) * 3600
    )

    # Positions are compared on the sky, never through pixel indices: cutouts sit on different grids,
    # so the target can be at x=50 in one frame and x=87 in another and still be the same star.
    # Frames whose target fell off a clipped cutout carry no measurement and take no part in this.
    usable = [item for item in measurements if item[2] is not None]
    motion = None
    if len(usable) >= 2:
        first_sky = usable[0][1].wcs.pixel_to_world(usable[0][2].x, usable[0][2].y)
        offsets_ra, offsets_dec, years = [], [], []
        for ref, cutout, measurement in usable:
            measured_sky = cutout.wcs.pixel_to_world(measurement.x, measurement.y)
            delta_ra, delta_dec = first_sky.spherical_offsets_to(measured_sky)
            offsets_ra.append(delta_ra.to_value("arcsec"))
            offsets_dec.append(delta_dec.to_value("arcsec"))
            years.append(Time(ref.mjd, format="mjd").decimalyear)

        motion = fit_motion(np.array(years), np.array(offsets_ra), np.array(offsets_dec))
        saturated_any = any(item[2].saturated for item in usable)
        fallback_any = any(item[2].centroid_fallback for item in usable)
        motion["reliable"] = not saturated_any and not fallback_any
    else:
        saturated_any = any(item[2].saturated for item in usable)

    frames = []
    for index, (ref, cutout, measurement) in enumerate(measurements):
        outliers = outlier_stats(crop, crop[index])
        measured = measurement is not None and not measurement.saturated
        # The flag mask does not need the target position, so a frame we could not measure still
        # reports how much of it is bad pixels: that is a statement about the frame, not the star.
        bad = (
            measurement.bad_fraction
            if measurement is not None
            else frame_bad_fraction(
                bad_mask(cutout.flags, bad_bits), np.isfinite(cutout.image)
            )
        )
        frames.append(
            {
                "date": ref.date.isoformat(),
                "t_min": ref.mjd,
                "obs_id": ref.obs_id,
                "file": f"{stem}_{ref.date.isoformat()}.webp",
                "bytes": webp_sizes[ref.date],
                "bad_fraction": round(bad, 5),
                "measure_skipped": measure_skipped.get(ref.obs_id),
                "outlier": {
                    key: None if value is None else round(value, 6)
                    for key, value in outliers.items()
                },
                "measure": {
                    "x": round(measurement.x, 3),
                    "y": round(measurement.y, 3),
                    "flux": round(measurement.flux, 4),
                    "flux_err": round(measurement.flux_err, 4),
                    "snr": None if measurement.snr is None else round(measurement.snr, 2),
                    "wavelength_um": (
                        None if measurement.wavelength_um is None
                        else round(measurement.wavelength_um, 3)
                    ),
                    "aperture_flagged": measurement.aperture_flagged,
                    "frames_available": ref.frames_available,
                }
                if measured
                else None,
                "saturated": bool(measurement is not None and measurement.saturated),
                "centroid_from_prediction": bool(
                    measurement is not None and measurement.centroid_fallback
                ),
            }
        )

    manifest = {
        "target": position.label,
        "name": position.name,
        "band": band,
        "size_deg": size_deg,
        "vmin": vmin,
        "vmax": vmax,
        "pixscale_arcsec": round(pixel_scale, 3),
        "generated_by": "python -m pipeline.cli build "
        f"--target {position.label} --band {band}",
        "note": (
            "One frame per observing date, all sharing the stretch above. Positions are measured on "
            "each frame's native pixel grid and compared on the sky. A measure of null means the "
            "target core saturated (only a lower flux bound exists) or that the target fell outside "
            "a clipped cutout, in which case measure_skipped says so. motion.reliable is false when "
            "a saturated core's centroid drifts with the roll angle of each visit."
        ),
        "collection": collection,
        "band_wavelength_um": BAND_EDGES_UM.get(band),
        "built": date.today().isoformat(),
        "n_frames": len(measurements),
        "n_bands_available": len(summary.bands),
        "available_bands": summary.bands,
        "position_note": (
            "Position propagated with the catalogue proper motion of the named target."
            if position.pm_ra_cosdec is not None and position.pm_dec is not None
            else "No proper motion available for this coordinate, so cutouts are centred on the "
            "position exactly as given; a fast mover may sit off-centre."
        ),
        "saturated_any": saturated_any,
        "frames": frames,
        "motion": motion,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    if write_manifest:
        (out_dir / f"{stem}.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest
