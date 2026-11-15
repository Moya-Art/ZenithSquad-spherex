"""Reading one SPHEREx level-2 cutout into arrays a sequence can use.

Extensions are addressed by name, never index: 1 IMAGE, 2 FLAGS, 3 VARIANCE, 4 ZODI, plus EPSF and
WCS-WAVE. ZODI is a model that is *not* subtracted from IMAGE, so we subtract it here — with no
variance update, which makes the reported errors optimistic. That is the same approximation the
official notebooks use; it is stated in the docstring rather than hidden.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS

EXPECTED_BUNIT = "mjysr"


@dataclass(frozen=True)
class Cutout:
    image: np.ndarray          # IMAGE - ZODI, MJy/sr
    raw: np.ndarray            # IMAGE as shipped, for provenance
    flags: np.ndarray          # int bit map
    variance: np.ndarray       # (MJy/sr)^2 per pixel
    header: fits.Header        # IMAGE header
    flag_header: fits.Header   # FLAGS header, carries the MSKN*/MSKD* bit names
    wcs: WCS                   # celestial only
    path: Path
    target_xy: tuple[float, float] | None = None
    wavelength_um: float | None = None


def check_bunit(header: fits.Header) -> None:
    bunit = str(header.get("BUNIT", "")).strip()
    if bunit.replace(" ", "").replace("/", "").lower() != EXPECTED_BUNIT:
        raise ValueError(f"unexpected IMAGE BUNIT {bunit!r}; this pipeline assumes MJy/sr")


def load_cutout(path: str | Path, sky=None) -> Cutout:
    """Load one cutout; when `sky` is given, resolve the target pixel and its wavelength."""
    path = Path(path)
    with fits.open(path, memmap=False) as hdul:
        header = hdul["IMAGE"].header.copy()
        check_bunit(header)
        wcs = WCS(header).celestial
        raw = hdul["IMAGE"].data.astype(float)
        zodi = hdul["ZODI"].data.astype(float)
        flags = hdul["FLAGS"].data.astype(np.int64)
        variance = hdul["VARIANCE"].data.astype(float)
        flag_header = hdul["FLAGS"].header.copy()
        target_xy = None
        wavelength_um = None
        if sky is not None:
            target_xy = tuple(float(value) for value in wcs.world_to_pixel(sky))
            wavelength_um = _wavelength_um(hdul, target_xy)

    return Cutout(
        image=raw - zodi,
        raw=raw,
        flags=flags,
        variance=variance,
        header=header,
        flag_header=flag_header,
        wcs=wcs,
        path=path,
        target_xy=target_xy,
        wavelength_um=wavelength_um,
    )


def _wavelength_um(hdul: fits.HDUList, target_xy: tuple[float, float]) -> float | None:
    """Central wavelength at a pixel, from the WAVE-TAB WCS that lives in another extension."""
    try:
        spectral = WCS(header=hdul["IMAGE"].header, fobj=hdul, key="W")
        spectral.sip = None
        with np.errstate(all="ignore"):
            wavelength = spectral.pixel_to_world(target_xy[0], target_xy[1])
        return float(wavelength.to_value("um"))
    except Exception:
        return None


def pixel_area_sr(wcs: WCS) -> float:
    return float(abs(np.linalg.det(wcs.pixel_scale_matrix)) * np.pi ** 2 / 180.0 ** 2)
