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
import logging
import os

from fastapi import FastAPI, Header, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from pipeline import catalog

from api.app import service

# Uvicorn configures its own loggers and leaves the root alone, so a build's own record — the bytes
# a cleanup freed, for instance — would otherwise be written to a logger nobody reads.
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

APP_VERSION = "0.7.0"

MANIFEST_MAX_AGE = 3600
FRAME_MAX_AGE = service.IMMUTABLE_SECONDS
BUILD_POLL_SECONDS = 2

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


def _resolve_position(
    target: str | None, ra: float | None, dec: float | None
) -> tuple[float, float]:
    """A slug resolves through `targets.json`; a raw coordinate has to be given in full.

    Rejecting a half-given coordinate here means the pipeline never builds a cube for Dec = None.
    """
    if target:
        entry = service.find_target(target)
        if entry is None:
            raise HTTPException(404, f"unknown target {target!r}")
        return float(entry["ra"]), float(entry["dec"])
    if ra is None or dec is None:
        raise HTTPException(422, "give either target=, or both ra= and dec=")
    return ra, dec


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
    response: Response,
    target: str | None = Query(default=None, pattern=r"^[a-z0-9_]+$"),
    ra: float | None = Query(default=None, ge=0.0, lt=360.0, description=RA_DESCRIPTION),
    dec: float | None = Query(default=None, ge=-90.0, le=90.0, description=DEC_DESCRIPTION),
    size: float = Query(default=service.DEFAULT_SIZE_DEG, gt=SIZE_MIN, le=SIZE_MAX),
    refresh: bool = Query(default=False),
) -> dict:
    """The 102 planes, the spectrum and the composite for one patch of sky.

    Built cubes answer `200` at once. A patch nobody has looked at answers `202` with what the build
    is doing, an ETA and whatever planes already exist — never a request that blocks on a 306 MiB tile
    download. Poll the same URL; no job id is needed because the coordinate *is* the job.
    """
    ra_value, dec_value = _resolve_position(target, ra, dec)
    payload, state = service.cube_state(
        ra_value, dec_value, target=target, size_deg=size, refresh=refresh
    )

    if state == "building":
        response.headers["X-Cache"] = "miss"
        response.headers["Retry-After"] = str(BUILD_POLL_SECONDS)
        response.headers["Cache-Control"] = "no-store"
        response.status_code = 202
        return payload

    response.headers["X-Cache"] = state
    response.headers["Cache-Control"] = (
        "no-store" if state == "failed" else f"public, max-age={MANIFEST_MAX_AGE}"
    )
    return payload


@app.get("/cube/plane")
def read_cube_plane(
    plane: int = Query(ge=0, le=1023),
    target: str | None = Query(default=None, pattern=r"^[a-z0-9_]+$"),
    ra: float | None = Query(default=None, ge=0.0, lt=360.0, description=RA_DESCRIPTION),
    dec: float | None = Query(default=None, ge=-90.0, le=90.0, description=DEC_DESCRIPTION),
    size: float = Query(default=service.DEFAULT_SIZE_DEG, gt=SIZE_MIN, le=SIZE_MAX),
    if_none_match: str | None = Header(default=None),
) -> Response:
    """One wavelength plane, greyscale, as WebP. The colormap is applied in the browser, so this
    response is the same bytes whatever palette is showing."""
    ra_value, dec_value = _resolve_position(target, ra, dec)
    try:
        data, state = service.cube_plane_webp(plane, ra_value, dec_value, size, target)
    except service.CubeNotReady as error:
        raise HTTPException(404, str(error)) from error

    digest = hashlib.sha1(data).hexdigest()
    headers = {
        "X-Cache": state,
        "Cache-Control": f"public, max-age={FRAME_MAX_AGE}, immutable",
        "ETag": f'"{digest}"',
    }
    if if_none_match is not None and digest in if_none_match:
        return Response(status_code=304, headers=headers)
    return Response(content=data, media_type="image/webp", headers=headers)


@app.get("/cube/composite")
def read_cube_composite(
    target: str | None = Query(default=None, pattern=r"^[a-z0-9_]+$"),
    ra: float | None = Query(default=None, ge=0.0, lt=360.0, description=RA_DESCRIPTION),
    dec: float | None = Query(default=None, ge=-90.0, le=90.0, description=DEC_DESCRIPTION),
    size: float = Query(default=service.DEFAULT_SIZE_DEG, gt=SIZE_MIN, le=SIZE_MAX),
    if_none_match: str | None = Header(default=None),
) -> Response:
    """The RGB composite, which is the only colour image the server renders."""
    ra_value, dec_value = _resolve_position(target, ra, dec)
    try:
        data, state = service.cube_composite_webp(ra_value, dec_value, size, target)
    except service.CubeNotReady as error:
        raise HTTPException(404, str(error)) from error

    digest = hashlib.sha1(data).hexdigest()
    headers = {
        "X-Cache": state,
        "Cache-Control": f"public, max-age={FRAME_MAX_AGE}, immutable",
        "ETag": f'"{digest}"',
    }
    if if_none_match is not None and digest in if_none_match:
        return Response(status_code=304, headers=headers)
    return Response(content=data, media_type="image/webp", headers=headers)


@app.get("/queue")
def read_queue(response: Response) -> dict:
    """Cube builds this instance knows about, newest first.

    It exists because a cube build is a server-side job, not a browser fetch: leaving the coordinate
    must not hide a build that is still running. Live state, so it is never cached.
    """
    response.headers["Cache-Control"] = "no-store"
    return {"jobs": service.queue_state()}


@app.get("/health")
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
