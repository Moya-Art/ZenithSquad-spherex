"""One patch of sky across all 102 SPHEREx wavelengths, from the all-sky HiPS cube.

The unit here is a **plane**, not a date: one 512x512 HEALPix tile of the DR1 all-sky cube holds all
102 wavelengths at every pixel, so a small crop of it is a spectrum that is already spatially aligned.
The tile is 306 MiB (`spherex_hipscube` §6 measures ~300 MB), which is why it is downloaded once per
HiPS version and cached, and why the planes are written to disk one at a time: the page can show plane
0 while plane 90 is still being rendered.

Three things are deliberately different from `sequence.py`, and each of them is a rule from §4 read in
the direction the cube needs:

* **One shared `asinh` stretch across all 102 planes**, not one per plane. An autoscaled plane series
  makes every band look equally bright and flattens the one thing a spectrum is for. §4's ban on
  per-frame autoscale applies to wavelengths for the same reason it applies to dates.
* **The RGB composite stretches each of its three channels on its own.** That is not a contradiction:
  a composite is a false-colour image, not a brightness comparison, and a shared scale would let the
  brightest band win every channel. §6 item 6 asks for exactly this.
* **NaN on a saturated core is filled before photometry, not just before display.** The archive stores
  NaN on the most saturated pixels, and one NaN inside the aperture would otherwise make the whole
  aperture sum NaN. The consequence is stated rather than hidden: a filled plane can only give a
  lower bound on the core flux, and `nan_pixels` per plane says how much of it was touched.

Spectra from this cube are **visualization grade** — the notebook says so twice. The UI says it too.
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import astropy.units as u
import hpgeom as hp
import numpy as np
import requests
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.stats import SigmaClip
from astropy.time import Time
from astropy.wcs import WCS
from photutils.aperture import (
    ApertureStats,
    CircularAnnulus,
    CircularAperture,
    aperture_photometry,
)

from pipeline import catalog
from pipeline.fits_io import check_bunit
from pipeline.render import global_stretch, save_webp
from pipeline.sequence import PositionSpec

S3_BUCKET = "https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com"
S3_CUBE_PREFIX = "dr1/hips5_cube/"
PROPERTIES_URL = "https://irsa.ipac.caltech.edu/data/hips/SPHEREx/spherex_allsky_cube/properties"
S3_NS = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}

DEFAULT_NORDER = 5
DEFAULT_SIZE_DEG = 0.3
MIN_CROP_PX = 160          # the smallest window that still holds the notebook's background annulus
APERTURE_PX = 5.0          # spherex_hipscube §6.3
ANNULUS_PX = (40.0, 60.0)
CORE_EXCLUDE_PX = 12.0     # kept out of the stretch, not out of the image (§3's saturated-star rule)
PERCENTILES = (1.0, 99.5)
COMPOSITE_ANCHORS_UM = (0.9, 2.3, 4.7)
PLANE_MAX_BYTES = 60_000
COMPOSITE_MAX_BYTES = 120_000
TILE_ATTEMPTS = 4
RETRY_WAIT_SECONDS = 10
REQUEST_TIMEOUT = 180
METADATA_CACHE = "cube_metadata.json"

NOTE = (
    "Visualization grade, not spectrophotometry: planes and the RGB composite are for looking at, "
    "and the spectrum is a quick look from a 5 px aperture with a 40-60 px background annulus. For "
    "science numbers use the IRSA SPHEREx Spectrophotometry tool. One asinh stretch is shared by all "
    "102 planes so that stepping through them shows real brightness change. Where the archive stores "
    "NaN on a saturated core the pixels are filled from the plane's finite ceiling, so those cores "
    "give only a lower bound."
)


class TileUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class Tile:
    version: str
    norder: int
    nside: int
    ipix: int
    dirid: int
    url: str


@dataclass(frozen=True)
class Plane:
    index: int
    detector: int
    subchan: int
    wavelength_um: float
    bandwidth_um: float

    @property
    def band(self) -> str:
        return f"D{self.detector}"


@dataclass(frozen=True)
class CubeRequest:
    position: PositionSpec
    size_deg: float = DEFAULT_SIZE_DEG
    out_root: Path = Path("data/fallback")
    cache_dir: Path = Path("data/cache")
    tile_cache_dir: Path = Path("data/cache/cube_tiles")
    version: str | None = None
    refresh: bool = False


@dataclass(frozen=True)
class TileWindow:
    """A small crop of one tile: the data plus everything the manifest needs to describe it."""

    cube: np.ndarray                 # (planes, rows, cols) MJy/sr, NaN filled
    hits: np.ndarray                 # (planes, rows, cols) contributing input pixels
    nan_pixels: np.ndarray           # (planes,) count filled per plane
    planes: tuple[Plane, ...]
    target_xy: tuple[float, float]   # in tile pixels
    crop_xy: tuple[float, float]     # in crop pixels
    crop: tuple[int, int, int, int]  # y0, y1, x0, x1
    tile_shape: tuple[int, int]
    pixel_scale_arcsec: float
    wcs: WCS
    version: str
    ipix: int
    dirid: int
    norder: int
    remote_bytes: int | None
    mosaic_epoch: float

    @property
    def crop_px(self) -> int:
        return int(self.cube.shape[1])


def _fetch_text(url: str, attempts: int = TILE_ATTEMPTS) -> str:
    wait = RETRY_WAIT_SECONDS
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(url, timeout=REQUEST_TIMEOUT) as response:
                return response.read().decode("utf-8", "replace")
        except Exception as error:
            last_error = error
            if attempt < attempts:
                time.sleep(wait)
                wait *= 2
    raise catalog.ArchiveUnknown(f"{url}: {type(last_error).__name__}: {last_error}")


def discover_version(attempts: int = TILE_ATTEMPTS) -> str:
    """Newest `hips_*` directory under the cube prefix. Never hardcoded: the notebook's
    `hips_20261026` will stop being current, and a hardcoded one would silently serve a stale sky."""
    listing = _fetch_text(
        f"{S3_BUCKET}/?list-type=2&delimiter=/&prefix={S3_CUBE_PREFIX}", attempts=attempts
    )
    try:
        root = ET.fromstring(listing)
    except ET.ParseError as error:
        raise catalog.SchemaError(f"cube version listing is not XML: {error}") from error
    found = sorted(
        Path(node.text.rstrip("/")).name
        for node in root.findall("s3:CommonPrefixes/s3:Prefix", S3_NS)
        if node.text
    )
    versions = [name for name in found if name.startswith("hips_")]
    if not versions:
        raise catalog.ArchiveUnknown(f"no HiPS cube version under {S3_CUBE_PREFIX}")
    return versions[-1]


def read_properties() -> dict:
    properties = {}
    for line in _fetch_text(PROPERTIES_URL).splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        properties[key.strip()] = value.strip()
    for required in ("hips_cube_depth", "hips_order", "hips_pixel_scale", "data_cube_crval3_arr"):
        if required not in properties:
            raise catalog.SchemaError(f"HiPS properties has no {required!r}")
    return properties


def discover(cache_dir: str | Path = "data/cache", refresh: bool = False) -> tuple[str, dict]:
    """Version and properties, with the last successful answer kept on disk so a rebuild is offline."""
    cache_path = Path(cache_dir) / METADATA_CACHE
    cached = None
    if cache_path.exists() and not refresh:
        try:
            cached = json.loads(cache_path.read_text())
        except json.JSONDecodeError:
            cached = None
    if cached is not None:
        return cached["version"], cached["properties"]

    version = discover_version()
    properties = read_properties()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps({"version": version, "properties": properties}, indent=2) + "\n"
    )
    return version, properties


def tile_for(ra: float, dec: float, version: str, norder: int = DEFAULT_NORDER) -> Tile:
    nside = 2 ** norder
    ipix = int(hp.angle_to_pixel(nside, ra, dec, nest=True, lonlat=True))
    dirid = (ipix // 10000) * 10000
    key = (
        f"{S3_CUBE_PREFIX}{version}/Norder{norder}/Dir{dirid}/Npix{ipix}_cube.fits"
    )
    return Tile(
        version=version,
        norder=norder,
        nside=nside,
        ipix=ipix,
        dirid=dirid,
        url=f"{S3_BUCKET}/{key}",
    )


def tile_path(tile: Tile, cache_dir: str | Path = "data/cache/cube_tiles") -> Path:
    return Path(cache_dir) / f"{tile.version}_N{tile.norder}_{tile.ipix}.fits"


def remote_size(tile: Tile) -> int | None:
    """Content-Length without downloading, so progress can report a percentage rather than bytes."""
    try:
        request = urllib.request.Request(tile.url, method="HEAD")
        with urllib.request.urlopen(request, timeout=30) as response:
            length = response.headers.get("Content-Length")
            return int(length) if length else None
    except Exception:
        return None


def ensure_tile(tile: Tile, cache_dir: str | Path = "data/cache/cube_tiles",
                refresh: bool = False, progress=None) -> Path:
    """Download the tile once, atomically. A killed download must not leave a file that reads as a
    cached tile: the partial bytes go to `.part` and are renamed only when complete."""
    destination = tile_path(tile, cache_dir)
    if destination.exists() and not refresh and destination.stat().st_size > 0:
        if progress:
            progress({"stage": "tile_cached", "bytes_done": destination.stat().st_size,
                      "bytes_total": destination.stat().st_size})
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(".part")

    wait = RETRY_WAIT_SECONDS
    last_error: Exception | None = None
    for attempt in range(1, TILE_ATTEMPTS + 1):
        try:
            with requests.get(tile.url, stream=True, timeout=REQUEST_TIMEOUT) as response:
                response.raise_for_status()
                total = int(response.headers.get("Content-Length") or 0) or None
                done = 0
                with partial.open("wb") as handle:
                    for chunk in response.iter_content(1 << 20):
                        handle.write(chunk)
                        done += len(chunk)
                        if progress:
                            progress({"stage": "downloading_tile", "bytes_done": done,
                                      "bytes_total": total})
            os.replace(partial, destination)
            return destination
        except Exception as error:
            last_error = error
            partial.unlink(missing_ok=True)
            if attempt < TILE_ATTEMPTS:
                time.sleep(wait)
                wait *= 2
    raise TileUnavailable(f"{tile.url}: {type(last_error).__name__}: {last_error}")


def crop_window(shape: tuple[int, int], x: float, y: float, size_deg: float,
                pixel_scale_arcsec: float) -> tuple[int, int, int, int]:
    """A square window containing the target, clamped inside the tile.

    It is never smaller than `MIN_CROP_PX`, because the background annulus reaches 60 px from the
    target and a smaller window would leave the annulus outside the data. Near a tile edge the window
    stops at the edge instead of wrapping, which clips the annulus — the notebook's own warning.
    """
    rows, cols = shape
    wanted = int(round(size_deg * 3600.0 / pixel_scale_arcsec))
    width = max(MIN_CROP_PX, min(wanted, min(rows, cols)))
    x0 = int(round(x)) - width // 2
    y0 = int(round(y)) - width // 2
    x0 = max(0, min(x0, cols - width))
    y0 = max(0, min(y0, rows - width))
    return y0, y0 + width, x0, x0 + width


def local_pixel_scale(wcs: WCS, x: float, y: float) -> u.Quantity:
    """Arcsec per pixel at (x, y), measured on the sky.

    A HEALPix tile's pixel solid angle is not constant — `spherex_hipscube` §6.3 makes the same point
    — so a single number for the whole tile would bias every flux that is not at the tile centre.
    """
    c0, c1, c2 = wcs.pixel_to_world([x, x + 1, x], [y, y, y + 1])
    d_lon1, d_lat1 = c0.spherical_offsets_to(c1)
    d_lon2, d_lat2 = c0.spherical_offsets_to(c2)
    area = np.abs(d_lon1 * d_lat2 - d_lat1 * d_lon2)
    return np.sqrt(area).to(u.arcsec) / u.pixel


def _spectral_table(hdul: fits.HDUList, depth: int) -> tuple[Plane, ...]:
    if "SPECTRAL_CHANNELS" in [hdu.name for hdu in hdul]:
        table = hdul["SPECTRAL_CHANNELS"].data
        return tuple(
            Plane(
                index=index,
                detector=int(table["DETECTOR"][index]),
                subchan=int(table["SUBCHAN"][index]),
                wavelength_um=float(table["WAVELENGTH"][index]),
                bandwidth_um=float(table["BANDWIDTH"][index]),
            )
            for index in range(min(len(table), depth))
        )
    raise catalog.SchemaError("the cube has no SPECTRAL_CHANNELS table; wavelengths are unknown")


def fill_nan(plane: np.ndarray, passes: int = 3) -> tuple[np.ndarray, int]:
    """Replace NaN with the brightest finite neighbour, in place of the archive's saturated cores.

    A handful of pixels is all it ever is (16 in one plane of the R Draconis tile), but one NaN inside
    the aperture makes photutils return NaN for the whole sum, so it has to go before photometry as
    well as before display. Returns the filled plane and how many pixels were touched.
    """
    missing = ~np.isfinite(plane)
    count = int(missing.sum())
    if count == 0:
        return plane, 0
    filled = plane.copy()
    for _ in range(passes):
        if not missing.any():
            break
        candidate = np.full_like(filled, -np.inf)
        padded = np.pad(np.where(np.isfinite(filled), filled, -np.inf), 1,
                        mode="constant", constant_values=-np.inf)
        rows, cols = filled.shape
        for shift_y in (0, 1, 2):
            for shift_x in (0, 1, 2):
                window = padded[shift_y:shift_y + rows, shift_x:shift_x + cols]
                candidate = np.maximum(candidate, window)
        replace = missing & np.isfinite(candidate)
        filled[replace] = candidate[replace]
        missing = ~np.isfinite(filled)
    if missing.any():
        ceiling = float(np.nanmax(filled)) if np.isfinite(filled).any() else 0.0
        filled[missing] = ceiling
    return filled, count


def read_window(path: str | Path, sky: SkyCoord, size_deg: float,
                tile: Tile | None = None, mosaic_epoch: float = 2025.5,
                remote_bytes: int | None = None) -> TileWindow:
    """Open the tile, resolve the target, and keep only a small crop of it in memory."""
    path = Path(path)
    with fits.open(path, memmap=True) as hdul:
        header = hdul["IMAGE"].header.copy()
        check_bunit(header)
        wcs3 = WCS(header, fobj=hdul)
        wcs = wcs3.celestial
        x, y = (float(value) for value in wcs.world_to_pixel(sky))
        if not (np.isfinite(x) and np.isfinite(y)):
            raise ValueError(f"{sky} does not project into tile {path.name}")
        # `proj_plane_pixel_scales` reports the projection's nominal scale (13.98" here); an HPX
        # tile's real pixel size is only correct measured on the sky, which is also why §4 cites
        # `local_pixel_scale` for cube photometry. Measured at the target: 12.88".
        pixel_scale = float(local_pixel_scale(wcs, x, y).value)
        rows, cols = hdul["IMAGE"].shape[1:]
        y0, y1, x0, x1 = crop_window((rows, cols), x, y, size_deg, pixel_scale)

        raw = np.array(hdul["IMAGE"].data[:, y0:y1, x0:x1], dtype=float)
        hits = np.array(hdul["NHITS"].data[:, y0:y1, x0:x1], dtype=np.int32)
        planes = _spectral_table(hdul, raw.shape[0])

    cube = np.empty_like(raw)
    nan_pixels = np.empty(raw.shape[0], dtype=int)
    for index in range(raw.shape[0]):
        cube[index], nan_pixels[index] = fill_nan(raw[index])

    return TileWindow(
        cube=cube,
        hits=hits,
        nan_pixels=nan_pixels,
        planes=planes,
        target_xy=(x, y),
        crop_xy=(x - x0, y - y0),
        crop=(y0, y1, x0, x1),
        tile_shape=(rows, cols),
        pixel_scale_arcsec=pixel_scale,
        wcs=wcs,
        version=tile.version if tile else "",
        ipix=tile.ipix if tile else -1,
        dirid=tile.dirid if tile else -1,
        norder=tile.norder if tile else DEFAULT_NORDER,
        remote_bytes=remote_bytes,
        mosaic_epoch=mosaic_epoch,
    )


def to_uint8_asinh(image: np.ndarray, vmin: float, vmax: float) -> np.ndarray:
    """`asinh` between vmin and vmax, which is what IRSA itself uses for these tiles
    (`hips_pixel_function`) and is the only monotonic stretch that survives a range this wide."""
    span = max(vmax - vmin, 1e-9)
    scaled = np.arcsinh((np.where(np.isfinite(image), image, vmin) - vmin) / span)
    ceiling = np.arcsinh(1.0)
    scaled = np.clip(scaled / ceiling, 0.0, 1.0)
    return np.flipud(np.rint(scaled * 255.0).astype(np.uint8))


def coverage(hits: np.ndarray) -> float:
    return float((hits > 0).mean()) if hits.size else 0.0


def spectrum_gear(window: TileWindow):
    """The aperture and annulus, built once and reused for all 102 planes."""
    x, y = window.crop_xy
    pixel_scale = local_pixel_scale(window.wcs, *window.target_xy)
    return {
        "x": x,
        "y": y,
        "aperture": CircularAperture((x, y), r=APERTURE_PX),
        "annulus": CircularAnnulus((x, y), r_in=ANNULUS_PX[0], r_out=ANNULUS_PX[1]),
        "clip": SigmaClip(sigma=3.0, maxiters=10),
        "pixel_sr": ((pixel_scale * u.pixel) ** 2).to(u.sr),
        "clipped": bool(
            y - ANNULUS_PX[1] < 0 or x - ANNULUS_PX[1] < 0
            or x + ANNULUS_PX[1] > window.crop_px - 1
            or y + ANNULUS_PX[1] > window.crop_px - 1
        ),
    }


def spectrum_point(index: int, plane: np.ndarray, hits: np.ndarray, gear: dict) -> dict:
    """The notebook's quick look for one plane: aperture sum, sigma-clipped annulus background, mJy
    via the local pixel solid angle.

    `noise_mjy` is a scatter estimate (annulus sigma x sqrt(aperture pixels)), not a calibrated error:
    the notebook's own function computes none, and a number with the wrong name would be worse than
    its absence.
    """
    if coverage(hits) == 0.0:
        return {"index": index, "flux_mjy": None, "noise_mjy": None,
                "annulus_clipped": gear["clipped"]}
    stats = ApertureStats(plane, gear["annulus"], sigma_clip=gear["clip"])
    background = float(stats.mean) if np.isfinite(stats.mean) else 0.0
    aperture_area = float(gear["aperture"].area_overlap(plane))
    photometry = aperture_photometry(plane, gear["aperture"])
    total = float(photometry["aperture_sum"][0]) - background * aperture_area
    # MJy/sr x sr = MJy, then astropy carries the rest of the conversion: 1 MJy is 1e9 mJy, so a
    # hand-written 1e3 here would report kJy and call it mJy.
    flux = (total * u.MJy / u.sr * gear["pixel_sr"]).to_value(u.mJy)
    scatter = float(stats.std) if np.isfinite(stats.std) else 0.0
    noise = (scatter * np.sqrt(max(aperture_area, 1.0)) * u.MJy / u.sr * gear["pixel_sr"]
             ).to_value(u.mJy)
    return {
        "index": index,
        "flux_mjy": round(flux, 6),
        "noise_mjy": round(noise, 6),
        "annulus_clipped": gear["clipped"],
    }


def spectrum_points(window: TileWindow) -> list[dict]:
    gear = spectrum_gear(window)
    return [
        spectrum_point(index, window.cube[index], window.hits[index], gear)
        for index in range(len(window.planes))
    ]


def composite_indices(window: TileWindow) -> list[int]:
    """Three planes by wavelength, not by eye (§6): nearest 0.9, 2.3 and 4.7 µm among planes that
    actually carry data. Returned long, middle, short so the caller can map them to R, G and B."""
    usable = [
        plane.index for plane in window.planes if coverage(window.hits[plane.index]) > 0.0
    ]
    if len(usable) < 3:
        raise ValueError("fewer than three planes carry data, so no composite is possible")
    picked: list[int] = []
    for anchor in COMPOSITE_ANCHORS_UM:
        choice = min(usable, key=lambda index: abs(
            window.planes[index].wavelength_um - anchor))
        if choice in picked:
            remaining = [index for index in usable if index not in picked]
            if not remaining:
                raise ValueError(f"the tile has no distinct plane near {anchor} um")
            choice = min(remaining, key=lambda index: abs(
                window.planes[index].wavelength_um - anchor))
        picked.append(choice)
    if len(set(picked)) != 3:
        raise ValueError("the composite picked the same plane twice")
    return sorted(picked, key=lambda index: window.planes[index].wavelength_um, reverse=True)


def rgb_composite(window: TileWindow, indices: list[int]) -> np.ndarray:
    """(rows, cols, 3) uint8, each channel stretched on its own."""
    channels = []
    for index in indices:
        plane = window.cube[index]
        finite = np.isfinite(plane) if np.isfinite(plane).any() else np.ones_like(plane, bool)
        vmin, vmax = np.percentile(plane[finite], PERCENTILES)
        if not np.isfinite(vmin) or not np.isfinite(vmax) or vmax <= vmin:
            vmin, vmax = float(np.nanmin(plane)), float(np.nanmax(plane))
        channels.append(to_uint8_asinh(plane, float(vmin), float(vmax)))
    return np.stack(channels, axis=-1)


def build_cube(request: CubeRequest, progress=None) -> dict:
    """Build one patch: download the tile if needed, then write planes one at a time.

    `progress` receives a dict rather than a line of text, because the API publishes these numbers to
    a waiting visitor: stage, planes_done, planes_total, bytes_done, bytes_total, message.
    """
    def report(**update):
        if progress:
            progress(update)

    version, properties = discover(request.cache_dir, refresh=request.refresh)
    version = request.version or version
    depth = int(properties["hips_cube_depth"])

    mosaic_mid = (float(properties["t_min"]) + float(properties["t_max"])) / 2.0
    mosaic_epoch = float(Time(mosaic_mid, format="mjd").decimalyear)

    if request.position.pm_ra_cosdec is not None and request.position.pm_dec is not None:
        ra, dec = catalog.propagate(
            request.position.ra,
            request.position.dec,
            request.position.pm_ra_cosdec,
            request.position.pm_dec,
            mosaic_epoch,
        )
        position_note = (
            f"Position propagated with catalogue proper motion to the mosaic's mean epoch "
            f"({mosaic_epoch:.2f}). At {properties['hips_pixel_scale']} deg/px the cube is coarse, "
            "but a fast mover still shifts by more than one cube pixel per decade."
        )
    else:
        ra, dec = request.position.ra, request.position.dec
        position_note = (
            "No proper motion for this coordinate, so the cube is read at the position exactly as "
            "given."
        )

    tile = tile_for(ra, dec, version)
    report(stage="locating_tile", message=f"Tile Npix{tile.ipix} of {version}", planes_done=0,
           planes_total=depth)
    path = ensure_tile(tile, request.tile_cache_dir, refresh=request.refresh,
                       progress=lambda update: report(
                           planes_done=0, planes_total=depth,
                           message="Downloading one all-sky cube tile", **update))

    window = read_window(path, SkyCoord(ra, dec, unit="deg"), request.size_deg, tile=tile,
                         mosaic_epoch=mosaic_epoch, remote_bytes=path.stat().st_size)

    out_dir = Path(request.out_root) / "cube"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = request.position.label
    if len(window.planes) != depth:
        raise catalog.SchemaError(
            f"tile has {len(window.planes)} planes, properties say {depth}")

    yy, xx = np.ogrid[: window.crop_px, : window.crop_px]
    core = np.hypot(xx - window.crop_xy[0], yy - window.crop_xy[1]) <= CORE_EXCLUDE_PX
    # Only positive pixels set the scale: a plane is mostly background at ~1e-2 MJy/sr, and letting
    # zeros and negatives into the percentiles drags p1 to zero and flattens everything. The core
    # disc is kept out of the percentiles (not out of the image) so a saturated star cannot set vmax.
    usable = [np.where(plane > 0.0, plane, np.nan) for plane in window.cube]
    vmin, vmax = global_stretch(usable, percentiles=PERCENTILES, exclude=core)

    planes: list[dict] = []
    points: list[dict] = []
    gear = spectrum_gear(window)
    for plane in window.planes:
        hits = window.hits[plane.index]
        covered = coverage(hits)
        name = f"{stem}_plane_{plane.index:03d}.webp"
        size = save_webp(
            to_uint8_asinh(window.cube[plane.index], vmin, vmax), out_dir / name,
            max_bytes=PLANE_MAX_BYTES,
        )
        entry = {
            "index": plane.index,
            "band": plane.band,
            "detector": plane.detector,
            "channel": plane.subchan,
            "wavelength_um": round(plane.wavelength_um, 4),
            "bandwidth_um": round(plane.bandwidth_um, 4),
            "blank": covered == 0.0,
            "coverage": round(covered, 4),
            "nan_pixels": int(window.nan_pixels[plane.index]),
            "bytes": size,
            "file": name,
        }
        planes.append(entry)
        point = spectrum_point(plane.index, window.cube[plane.index], hits, gear)
        points.append(point)
        # The plane and its spectrum point travel with the progress update, so a waiting visitor can
        # render what exists instead of waiting for plane 102.
        report(
            stage="rendering_planes",
            planes_done=len(planes),
            planes_total=depth,
            message=f"Rendering plane {len(planes)} of {depth} "
                    f"({plane.wavelength_um:.3f} um)",
            plane=entry,
            point=point,
        )

    indices = composite_indices(window)
    rgb_name = f"{stem}_rgb.webp"
    rgb_bytes = save_webp(rgb_composite(window, indices), out_dir / rgb_name,
                          max_bytes=COMPOSITE_MAX_BYTES)

    channels = []
    for channel, index in zip(("R", "G", "B"), indices):
        channels.append({
            "channel": channel,
            "index": index,
            "band": window.planes[index].band,
            "wavelength_um": round(window.planes[index].wavelength_um, 4),
        })

    finite_flux = [point["flux_mjy"] for point in points if point["flux_mjy"] is not None]
    peak = max(finite_flux) if finite_flux else None
    peak_point = next(
        (point for point in points if point["flux_mjy"] == peak), None) if peak else None

    manifest = {
        "state": "ready",
        "target": request.position.label,
        "name": request.position.name,
        "ra": round(ra, 6),
        "dec": round(dec, 6),
        "size_deg": request.size_deg,
        "crop_px": window.crop_px,
        "crop_arcmin": round(window.crop_px * window.pixel_scale_arcsec / 60.0, 2),
        "pixscale_arcsec": round(window.pixel_scale_arcsec, 3),
        "target_xy": [round(window.crop_xy[0], 2), round(window.crop_xy[1], 2)],
        "tile": {
            "norder": tile.norder,
            "ipix": tile.ipix,
            "dirid": tile.dirid,
            "version": tile.version,
            "url": tile.url,
            "bytes": window.remote_bytes,
            "shape": list(window.tile_shape),
            "crop": list(window.crop),
            "mosaic_epoch": round(mosaic_epoch, 2),
        },
        "stretch": {"mode": "asinh", "vmin": round(float(vmin), 6),
                    "vmax": round(float(vmax), 6)},
        "planes": planes,
        "composite": {
            "file": rgb_name,
            "bytes": rgb_bytes,
            "channels": channels,
            "note": "Each channel is stretched on its own: a composite is a false-colour image, "
                    "not a brightness comparison.",
        },
        "spectrum": {
            "unit": "mJy",
            "aperture_px": APERTURE_PX,
            "annulus_px": list(ANNULUS_PX),
            "pixscale_arcsec": round(window.pixel_scale_arcsec, 3),
            "peak_index": None if peak_point is None else peak_point["index"],
            "points": points,
        },
        "depth": depth,
        "blank_planes": [plane["index"] for plane in planes if plane["blank"]],
        "notes": {
            "spectrum": "Quick-look aperture photometry; noise_mjy is a scatter estimate, not a "
                        "calibrated error.",
            "position": position_note,
            "quality": NOTE,
        },
        "generated_by": f"python -m pipeline.cli cube --target {request.position.label}",
        "built": date.today().isoformat(),
    }

    (out_dir / f"{stem}.json").write_text(json.dumps(manifest, indent=2) + "\n")
    report(stage="done", planes_done=depth, planes_total=depth, message="Cube complete")
    return manifest
