"""Global stretch and WebP encoding.

One brightness scale for a whole sequence, computed once over the concatenation of every frame.
Per-frame autoscale manufactures fake variability — a star appears to flare because the contrast
changed — and it is the worst bug this project can ship.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

PERCENTILES = (1.0, 99.5)
QUALITY_LADDER = (85, 75, 65, 55)
MAX_BYTES = 60_000


def global_stretch(
    images: list[np.ndarray],
    percentiles: tuple[float, float] = PERCENTILES,
    exclude: np.ndarray | None = None,
) -> tuple[float, float]:
    """Percentiles over every frame at once. `exclude` drops pixels from the *scale*, not from the
    image — used to keep a saturated star's halo from setting vmax and crushing the field."""
    usable = []
    for image in images:
        finite = np.isfinite(image)
        if exclude is not None:
            finite &= ~exclude
        usable.append(image[finite])
    usable = [values for values in usable if values.size]
    if not usable:
        raise ValueError("no finite pixels across the sequence")
    pooled = np.concatenate(usable)

    vmin, vmax = np.percentile(pooled, percentiles)
    if not np.isfinite(vmin) or not np.isfinite(vmax) or vmax <= vmin:
        raise ValueError(f"cannot stretch: vmin={vmin} vmax={vmax}")
    return float(vmin), float(vmax)


def to_uint8(image: np.ndarray, vmin: float, vmax: float) -> np.ndarray:
    scaled = (image - vmin) / (vmax - vmin)
    scaled = np.clip(np.nan_to_num(scaled, nan=0.0, posinf=1.0, neginf=0.0), 0.0, 1.0)
    # FITS row 0 is the bottom of the image; flip so north is up.
    return np.flipud(np.rint(scaled * 255.0).astype(np.uint8))


def to_uint8_asinh(image: np.ndarray, vmin: float, vmax: float) -> np.ndarray:
    """`asinh` between vmin and vmax, which is what IRSA itself uses for these tiles
    (`hips_pixel_function`) and is the only monotonic stretch that survives a range this wide.

    Both the date sequence and the wavelength cube render through this, so the two plates of one
    page agree about what "bright" means. A linear clip is kept above for the Phase 1 preview PNGs,
    which are not the app.
    """
    span = max(vmax - vmin, 1e-9)
    scaled = np.arcsinh((np.where(np.isfinite(image), image, vmin) - vmin) / span)
    ceiling = np.arcsinh(1.0)
    scaled = np.clip(scaled / ceiling, 0.0, 1.0)
    return np.flipud(np.rint(scaled * 255.0).astype(np.uint8))


def save_webp(pixels: np.ndarray, path: str | Path, max_bytes: int = MAX_BYTES) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    picture = Image.fromarray(pixels)
    size = 0
    for quality in QUALITY_LADDER:
        picture.save(path, format="WEBP", quality=quality, method=6)
        size = path.stat().st_size
        if size <= max_bytes:
            return size
    return size
