"""HTTP routes for the SPHEREx sky-time viewer.

Every handler is a plain `def`, so FastAPI runs it in its threadpool: `pipeline` is blocking
(`urllib`, `requests`, `astropy`) and an `async def` handler would stall the event loop for the length
of a FITS download.

Failure identities, which is the only interesting part of this file:

* zero frames in the archive  -> 404, "measured zero", never an empty 200;
* IRSA unreachable            -> 503, or 200 from the cache with `stale: true`;
* a response we could not parse -> 502;
* parameters out of range     -> 422;
* anything else               -> 503 with a named cause. Never a bare 500, and never a FITS body.
"""

from __future__ import annotations

import hashlib
import os

from fastapi import FastAPI, Header, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from pipeline import catalog

from api.app import service

APP_VERSION = "0.5.0"

MANIFEST_MAX_AGE = 3600
FRAME_MAX_AGE = service.IMMUTABLE_SECONDS

CORS_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",")
    if origin.strip()
]

app = FastAPI(
    title="SPHEREx Sky-Time API",
    version=APP_VERSION,
    description=(
        "One patch of sky, across its SPHEREx observation dates. Candidates for inspection, "
        "not discoveries."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "HEAD", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-Cache", "ETag", "Cache-Control", "Content-Length"],
    max_age=600,
)

RA_DESCRIPTION = "Right ascension, degrees (J2000)"
DEC_DESCRIPTION = "Declination, degrees (J2000)"
SIZE_DESCRIPTION = "Field size, degrees"
BAND_PATTERN = r"^D[1-6]$"
BAND_DESCRIPTION = "Detector band, D1–D6"
SIZE_MIN, SIZE_MAX = 0.0, 2.0


def _manifest_response(response: Response, manifest: dict, state: str) -> dict:
    response.headers["X-Cache"] = state
    response.headers["Cache-Control"] = (
        "no-store" if manifest.get("stale") else f"public, max-age={MANIFEST_MAX_AGE}"
    )
    return manifest


@app.get("/targets")
def read_targets(response: Response) -> dict:
    """The five targets, verbatim from `data/targets.json`."""
    response.headers["Cache-Control"] = f"public, max-age={MANIFEST_MAX_AGE}"
    return {"targets": service.targets()}


@app.get("/frames")
def read_frames(
    response: Response,
    ra: float | None = Query(default=None, ge=0.0, lt=360.0, description=RA_DESCRIPTION),
    dec: float | None = Query(default=None, ge=-90.0, le=90.0, description=DEC_DESCRIPTION),
    band: str | None = Query(default=None, pattern=BAND_PATTERN, description=BAND_DESCRIPTION),
    size: float = Query(
        default=service.DEFAULT_SIZE_DEG, gt=SIZE_MIN, le=SIZE_MAX, description=SIZE_DESCRIPTION
    ),
    target: str | None = Query(
        default=None, pattern=r"^[a-z0-9_]+$", description="A slug from /targets"
    ),
    refresh: bool = Query(default=False, description="Rebuild even if the cache answers"),
) -> dict:
    """The time sequence for a coordinate: epochs, one shared stretch, and one frame per date."""
    if target:
        entry = service.find_target(target)
        if entry is None:
            raise HTTPException(404, f"unknown target {target!r}; see /targets")
        ra, dec = float(entry["ra"]), float(entry["dec"])
    elif ra is None or dec is None:
        raise HTTPException(422, "give either target=<slug> or ra=<deg>&dec=<deg>")

    try:
        manifest, state = service.live_sequence(
            ra, dec, band=band, size_deg=size, refresh=refresh, target=target
        )
    except service.NoCoverage as error:
        raise HTTPException(404, str(error)) from error
    except catalog.ArchiveUnknown as error:
        # A cached answer is still true — an `obs_id` never changes — so serve it and say it is old
        # rather than making a flaky proxy look like an empty sky.
        cached = service.cached_sequence(ra, dec, band, size) if band else None
        if cached is not None:
            cached["stale"] = True
            return _manifest_response(response, cached, "stale")
        raise HTTPException(503, f"IRSA did not answer: {error}") from error
    except catalog.SchemaError as error:
        raise HTTPException(502, f"IRSA answered something we cannot parse: {error}") from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error

    return _manifest_response(response, manifest, state)


@app.get("/preview")
def read_preview(
    obs_id: str = Query(min_length=1),
    ra: float = Query(ge=0.0, lt=360.0, description=RA_DESCRIPTION),
    dec: float = Query(ge=-90.0, le=90.0, description=DEC_DESCRIPTION),
    band: str = Query(pattern=BAND_PATTERN, description=BAND_DESCRIPTION),
    size: float = Query(gt=SIZE_MIN, le=SIZE_MAX, description=SIZE_DESCRIPTION),
    if_none_match: str | None = Header(default=None),
) -> Response:
    """One exposure, stretched with its sequence's `vmin`/`vmax`, as WebP. Never FITS."""
    try:
        data, state = service.preview_webp(obs_id, ra, dec, band, size)
    except service.UnknownFrame as error:
        raise HTTPException(404, str(error)) from error
    except service.NoCoverage as error:
        raise HTTPException(404, str(error)) from error
    except catalog.ArchiveUnknown as error:
        raise HTTPException(503, f"IRSA did not answer: {error}") from error
    except catalog.SchemaError as error:
        raise HTTPException(502, f"IRSA answered something we cannot parse: {error}") from error

    digest = hashlib.sha1(data).hexdigest()
    headers = {
        "X-Cache": state,
        "Cache-Control": f"public, max-age={FRAME_MAX_AGE}, immutable",
        "ETag": f'"{digest}"',
    }
    if if_none_match is not None and digest in if_none_match:
        return Response(status_code=304, headers=headers)

    return Response(content=data, media_type="image/webp", headers=headers)


@app.get("/cube")
def read_cube(
    ra: float = Query(ge=0.0, lt=360.0, description=RA_DESCRIPTION),
    dec: float = Query(ge=-90.0, le=90.0, description=DEC_DESCRIPTION),
    size: float = Query(default=service.DEFAULT_SIZE_DEG, gt=SIZE_MIN, le=SIZE_MAX),
) -> Response:
    """Registered, not served: the 102 planes and the spectrum are Phase 6's `pipeline/cube.py`."""
    raise HTTPException(
        501,
        detail=(
            "the 102-band cube is not served yet: it arrives with pipeline/cube.py in Phase 6. "
            "Time mode is live at /frames."
        ),
    )


@app.get("/healthz")
def healthz() -> dict:
    """Liveness, plus whether the archive has answered and the cache can be written."""
    return {**service.health(), "version": APP_VERSION}


@app.exception_handler(catalog.ArchiveUnknown)
def archive_unknown(_request, error: catalog.ArchiveUnknown) -> JSONResponse:
    return JSONResponse(
        status_code=503, content={"detail": f"IRSA did not answer: {error}"}
    )


@app.exception_handler(catalog.SchemaError)
def archive_schema(_request, error: catalog.SchemaError) -> JSONResponse:
    return JSONResponse(
        status_code=502, content={"detail": f"IRSA answered something we cannot parse: {error}"}
    )
