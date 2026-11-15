# Changelog

Notable changes to this project, recorded one entry per build phase. Newest phase first.
Each entry names the pull request and commit that landed it.

**The build plan lives outside this repository.** So any edit to it — a corrected number, a changed
method, a rule that turned out to be wrong — is recorded here, section by section, in the phase's
`### Plan changes` block. That block is how a teammate learns the plan moved without being sent the
document again.

Entry format:

```markdown
## Phase N — <name> — YYYY-MM-DD
Merged in [#N](pull-request-url). Commit `<sha>`.

### Added / Changed / Fixed / Removed
- what changed, and why it matters

### Plan changes
- every edit to the build plan: which section, what it said before, what it says now, and why
```

---

## Phase 6 — Spectrum and colour (102 bands) — 2026-11-15

Merged in [#12](https://github.com/Moya-Art/ZenithSquad-spherex/pull/12). Squash-merged onto `main`.

### Added

- `pipeline/cube.py` — the all-sky HiPS cube: version discovery from the S3 listing (never hardcoded),
  `properties` parsing, tile download with byte-counted progress, a 160 × 160 crop, one pooled `asinh`
  stretch for all 102 planes, one greyscale WebP per plane, the spectrum, and the RGB composite.
  Reuses `render.global_stretch`/`save_webp`, `fits_io.check_bunit` and `catalog.propagate` rather than
  growing a second copy of each.
- `pipeline/cli.py cube` — `--target` or `--ra/--dec`, printing a row per plane as it completes and a
  summary of stretch, composite wavelengths and spectrum peak. Same exit codes as `build`.
- `api/app/main.py` — `/cube` is real (was a `501`), plus `/cube/plane` and `/cube/composite`.
  `/cube?target=` serves a committed artifact; `/cube?ra=&dec=` answers `202` with build progress.
- `api/app/service.py` — the cube build queue: one daemon worker, one job per cache key, progress on
  disk, `updated_at` older than 120 s treated as a dead job and re-enqueued.
- `api/app/cache.py` — `cube_key` (no band: a cube *is* the spectrum), `cubes/<key>/` with
  `cube.json`, `progress.json` and the plane files.
- `data/fallback/cube/` — R Draconis: 102 planes, the composite, and the manifest (740 KB total).
- `web/src/colormaps.ts` — greyscale plus 10 palettes as anchor sets interpolated to 256 entries, and a
  randomizer that walks lightness monotonically so a random ramp stays readable.
- `web/src/CubeView.tsx` — plane stage, wavelength scrubber, palette thumbnails rendered from the
  actual plane, composite with its three bands named, and the build progress strip.
- `web/src/SpectrumChart.tsx` — hand-rolled SVG, one user unit per CSS pixel, with the notebook's
  emission-line markers (Paβ, H⁻, Paα, Brγ, Brβ, PAH, Brα, CO) and nulls that break the line.
- `tests/test_cube.py`, `tests/test_api_cube.py`, `tests/test_cube_artifact.py` — 36 tests, none
  touching the network.

### Changed

- `web/src/App.tsx` gains a Time / Spectrum switch; the band switcher hides in spectrum mode, and the
  global Space/←/→ map stands down so the plane scrubber owns the arrows.
- `web/src/viewState.ts` gains `mode`, `plane` and `cmap`; `web/src/data.ts` gains the `Cube` types,
  `loadCube` and the plane/composite URL helpers.
- `tests/test_api_routes.py` — the two assertions that `/cube` answers `501` are replaced. The
  no-FITS test now patches `service.cube_state`, because an unpatched `/cube` would start a real
  306 MiB download inside the test suite.

### Measured

- Tile: **320 909 760 B (306 MiB)**, identical for every Norder-5 tile, downloaded in **72.6 s at
  4.4 MB/s**. One tile covers 1.83°, so every coordinate inside it is free afterwards.
- R Draconis: crop 160 × 160 px = 34.35′, stretch `asinh` `vmin = 0.005827` `vmax = 1.074214` MJy/sr,
  102 planes at 3.4–9.4 KB each, composite 2.7 KB, **740 KB total**.
- Spectrum: 666 mJy at 0.753 µm → **15 575 mJy at 4.988 µm**, peak at plane 101. Target 236× the field
  at 0.753 µm and 8 169× at 4.988 µm.
- Cold API build: `202` → byte progress (ETA 253 s → 86 s over nine polls) → rendering 102 planes in
  about **4 s** from the cached tile → `200`, `X-Cache: hit`.
- `pytest tests/ -q` → **113 passed** (77 + 36). `npm run build` → 256 kB / 80 kB gzipped.
  `npm run lint` → 0 errors, 3 warnings (two pre-existing, one new effect that synchronises with a
  poll).

### Decisions

- **One shared `asinh` stretch for all 102 planes.** A per-plane autoscale would make every band look
  equally bright and flatten the spectrum, which is §4's fake-variability rule one axis over. Linear
  is wrong too: the cube spans −1419 → +11348, so most planes would sit at the bottom of the ramp.
  `asinh` is what IRSA renders these tiles with (`hips_pixel_function`).
- **The composite stretches each channel on its own.** Tried both ways; a shared scale washed the
  colour out. A composite is a false-colour image, not a brightness comparison.
- **`local_pixel_scale`, never `proj_plane_pixel_scales`.** The projection says 13.983″/px where the
  sky says 12.883″; an HPX pixel's solid angle is not constant.
- **The colormap is a browser-side lookup table** over an already-downloaded greyscale plane, so 11
  palettes cost one pass over a 160 × 160 buffer and no bytes.
- **A cold coordinate is a job, not a request.** Rendering 102 planes is fast; the 306 MiB tile is not.
  A blocking HTTP request would time out on the thing that actually takes the time.
- **Committed artifacts answer first, then the cache, then the queue.** The five targets must never
  wait in front of a judge.

### Findings that changed the plan

- **The dichroic planes are blank by design** — indices 50 and 51 (D3 ch 17, D4 ch 1) have zero
  `NHITS` everywhere. They are flagged and indexed rather than dropped: dropping them would mislabel
  every wavelength after them.
- **`index = 17·(detector−1) + (subchan−1)` holds**, confirmed against `SPECTRAL_CHANNELS` for all 102
  rows, so `DETECTOR`/`SUBCHAN` come from the table rather than from arithmetic.
- **R Draconis sits 19.6 px from its tile edge**, so its 40–60 px annulus is ~61 % in-frame and 100 of
  102 planes report `annulus_clipped`. This is the notebook's own documented behaviour; the flag is
  per plane so a background estimate built from a partial ring is never silent.
- **`measure.py` converts MJy → mJy with `× 1e3`, which is kJy.** Found while building the cube's own
  conversion: astropy units give 5 417 mJy for plane 93, the same arithmetic with `1e3` gives 0.0054.
  SNR is unaffected and no committed value is wrong today, because R Draconis saturates and every
  `measure` in its manifest is `null`. **Open for Phase 7**, where an unsaturated target first makes
  the number visible. Not changed here: it moves a Phase 3 rule and the plan did not ask for it.
- **A windowed range read of the tile was abandoned** — `fsspec`'s HTTP filesystem needs `aiohttp`,
  which is not installed, and one full download serves a whole 1.83° tile afterwards.

### Plan changes

- **§6 Phase 6 gains an asynchronous build path.** Was a synchronous route; now a queue with
  `progress.json`, `202` + `Retry-After`, progressive planes, a shared cache and committed artifacts.
  Proposed and approved before implementation, as a request from the team.
- **§6 Phase 6 gains the colormap picker** (greyscale + 10 palettes + randomizer). Not in the brief;
  adjacent to "think creatively about how to display those 102 infrared bands", and free because the
  planes are greyscale and the palette is applied in the browser.
- **`/cube` signature.** `ra`/`dec` are now optional in favour of `target=`, so a committed artifact
  can be served without pretending to be a coordinate. `/frames` already takes both. A request with
  neither is a `422` before it reaches the pipeline.
- **§6 Phase 6 item 4 gains a stretch mode.** One pooled `asinh` stretch for the 102 planes, positive
  pixels only, excluding a 12 px disc around the target. Item 6's independent per-channel stretch is
  unchanged.
- **§6 Phase 6 item 6 gains the channel order and the anchor wavelengths.** R = longest, B = shortest;
  planes nearest 0.9, 2.3 and 4.7 µm chosen from the wavelengths array at build time.
- **§5 repository tree gains** `data/fallback/cube/`, `web/src/CubeView.tsx`,
  `web/src/SpectrumChart.tsx`, `web/src/colormaps.ts`, `tests/test_cube*.py`.
- **§7 verification, cube-vs-time-mode flux** — recorded as documentation rather than a tolerance.
  The cube is 12.883″/px with a 5 px aperture (64″); time mode is 6.15″/px with 3 px (18″); the mosaic
  stacks every contributing exposure where a frame is one exposure. R Draconis cannot even provide the
  comparison, because its time-mode measurement is null.

### Verification

- `pytest tests/ -q` → 113 passed, no network in any of them.
- `npm run build` → clean (`tsc -b` included); `npm run lint` → 0 errors.
- Live: `/cube?target=r_dra` → `200` `X-Cache: committed`, 102 planes, composite present;
  `/cube?ra=90&dec=20` → `202` then `200` `X-Cache: hit`; `/cube/plane` → `image/webp` with an ETag
  and `304` on `If-None-Match`; `/cube/plane?plane=101` → `404` while the build was still rendering;
  `/cube` with no position → `422`; `?target=not_a_target` → `404`.
- The build was watched end to end: queued → byte progress on the 306 MiB tile → planes 1, 30, 69,
  102 arriving in the poll payload → ready, while nothing but the server was running.
- Opened and looked at: planes at 0.75 / 2.29 / 4.70 µm, the blank plane 50, and the composite. The
  first attempt had a black square in the core of the star — NaN at the saturated centre — which is
  the fill rule in §4.5 of the phase note.

### Notes for the next phase

- Phase 7 builds the other four cubes with the same one-line command; only R Draconis is committed.
  `data/fallback/cube/` is already copied into `dist`, and `.webp`/`.json` already have content types,
  so nothing in `vite.config.ts` changes.
- **WISE 0855's cube is the one that matters.** Its blink has no second season and no single-frame
  detection; the cube is where it can appear at all.
- The cold cube path on Cloud Run needs more than `--memory 2Gi`: `/tmp` is memory-backed and the tile
  is 306 MiB. Phase 8 either raises the limit or moves cube builds into the Job.
- `measure.py`'s mJy conversion (§ Findings) should be settled before an unsaturated target's flux is
  shown to anyone.

---

## Phase 5 — API — 2026-11-15

Merged in [#9](https://github.com/Moya-Art/ZenithSquad-spherex/pull/9). Squash-merged onto `main`.

### Added

- `api/app/main.py` — `/targets`, `/frames`, `/preview`, `/cube` (501), `/healthz`. Every handler is a
  plain `def`, so FastAPI runs it in its threadpool: `pipeline` blocks on `urllib`, `requests` and
  `astropy`, and an `async def` route would stall the event loop for the length of a FITS download.
- `api/app/service.py` — the only module that imports `pipeline`. `live_sequence` builds on a cold key
  and returns `(manifest, "miss"|"hit")`; `preview_webp` resolves an `obs_id` through the cached
  manifest, then a fresh SIA query, then a 404. `_BUILD_LOCK` serialises cold builds, because Cloud
  Run runs requests concurrently and each build fans out to eight workers against a ~12-request limit.
- `api/app/cache.py` — sequence key `sha1(f"{ra:.5f}:{dec:.5f}:{band}:{size}")` holding the manifest
  and its WebPs, and frame key `sha1(f"{obs_id}:{ra:.5f}:{dec:.5f}:{size}")` holding one WebP. Writes
  are atomic, so a killed build cannot leave a manifest that reads as a hit.
- `api/Dockerfile` — `python:3.14-slim`, the same interpreter the venv was frozen from. Not deployed;
  Cloud Run, Artifact Registry and Vercel stay in Phase 8.
- `pipeline/sequence.py` — `build_from_position(PositionSpec)`, so a raw coordinate builds the same
  sequence a named target does. `build_sequence(request)` is now a thin wrapper over it.
- `pipeline/measure.py` — `TargetOutsideFrame`.
- `tests/test_api_cache.py`, `tests/test_api_routes.py` — 26 tests, no network.
- `web/src/data.ts` — `/targets` and `/frames` first, committed file as the fallback for any failure
  that is not a 404 or a 422. `frameUrl` prefers the API's per-frame `url`.
- `web/vite.config.ts` — `/api` proxy to `127.0.0.1:8000`, so dev is same-origin and needs no CORS.

### Measured

- Cold `/frames` for `r_dra` D1: **31.5 s**, `X-Cache: miss`; the same request immediately after:
  **0.04 s**, `X-Cache: hit`. 21 frames, `vmin = 0.024`, `vmax = 3.985`, the same stretch the
  committed manifest has — two independent builds agreeing.
- Stage 0 probe against the live archive: Barnard D6, 14 dates, 117 s with FITS cached (one 502
  retry), 179 MB peak RSS, nothing downloaded; raw coordinate RA 90 Dec +20 with an empty cache,
  12 dates, **67 s**, **52.9 MB** downloaded, 215 MB peak RSS. Both well inside `--memory 2Gi
  --timeout 600`, so the live default field size stays **0.3°**.
- A coordinate 70° from every named target (RA 200, Dec −80) returns a full sequence, so the arbitrary
  coordinate path is real and not only the five slugs.
- `pytest tests/ -q` → **77 passed** (51 + 26). `npm run build` → 238.5 kB / 74.8 kB gzipped.
  `npm run lint` → 0 errors, 2 pre-existing warnings.

### Decisions

- **A cold `/frames` builds the sequence, it does not list epochs.** An epoch list leaves the renderer
  to stretch each frame on request, and a per-frame scale manufactures variability that is not in the
  sky (§4). The price is a slow first request; every later one is a file read.
- **`/preview` uses the sequence's stretch.** It resolves `obs_id` through the cached manifest first,
  because otherwise every image request would re-query the archive.
- **Failures keep their identity.** Zero frames → 404 saying it is a measured zero. Unreachable
  archive → 503, or 200 + `stale: true` + `no-store` when a cached manifest can answer. Unparseable
  → 502. Out-of-range parameters → 422. A bare 500 is never the answer to an IRSA afternoon.
- **Cold builds are serialised.** `--concurrency 4` times eight workers would break IRSA's limit; a
  second visitor waits and usually finds the first build's cache.
- **The API is not the only source.** `data.ts` falls back to the committed sequence, so the venue
  Wi-Fi cannot leave a blank screen. Verified by stopping the API and reloading.
- **`/cube` is a registered 501.** The 102 planes arrive with Phase 6's `pipeline/cube.py`.
- **A target outside a clipped cutout is a fact, not a crash.** IRSA clips at the detector edge and
  the predicted pixel can land past the returned array; that frame is `measure: null` with
  `measure_skipped` explaining it, and takes no part in the motion fit. `bad_fraction` is still
  computed, because the flag mask does not need the target position.

### Findings that changed the plan

- **A raw coordinate crashed the pipeline.** The probe died on `IndexError: index 87 is out of bounds
  for axis 0 with size 81` — the target was outside a 175×81 clipped cutout. Fixed here, not deferred.
- **Barnard's Star is flagged `BLOOM` on its core in all 14 D6 frames, with no `OVERFLOW`**, at
  ~1 000–1 400 MJy/sr. Phase 3's rule counts `BLOOM` as saturation, so every Barnard frame has no
  photometry. **Open for Phase 7:** is `BLOOM` alone a saturated core, or bloom-affected pixels around
  a bright neighbour? If the latter, the saturation set becomes `OVERFLOW` only — that changes a
  Phase 3 rule, so it was not changed here.
- **The motion panel ignored `motion.reliable`.** The centroid fit runs whether or not the photometry
  is usable, so Barnard produced "moved 8.4″ … consistent with real motion" out of saturated cores.
  Phase 3's own note said the panel must read `reliable` first. It now says "not measurable".

### Plan changes

- **§6 Phase 5, `/frames`** — "live SIA query → epoch list" became "the whole sequence is built, one
  shared stretch, cached". Proposed and approved before implementation: the epoch-list version cannot
  honour §4's single stretch.
- **§6 Phase 5, `/cube`** — was in Phase 5's route list. Now a registered `501`; the 102 planes and
  the spectrum stay with Phase 6. Proposed and approved.
- **§6 Phase 5, cache key** — the per-frame key is kept and a sequence-level key
  `sha1(f"{ra:.5f}:{dec:.5f}:{band}:{size}")` was added, because a single stretch only exists per
  sequence, not per frame.
- **§6 Phase 5, "5 decimals ≈ 1″"** — arithmetic correction, not a rule change: five decimals of a
  degree is **0.036″**. The rounding still means a re-click is one entry; a click an arcsecond away is
  a new one.
- **§6 Phase 5, concurrency** — added that cold builds are serialised inside the process, with the
  ~12-request IRSA limit as the reason.
- **§5 repository tree** — `api/app/main.py` gained `app/service.py`, `app/cache.py` and
  `api/Dockerfile`.

### Verification

- `pytest tests/ -q` → 77 passed, no network in any of them.
- Live curl: `/healthz`, `/targets`, cold/warm `/frames`, cold/warm `/preview`, `/cube` → 501,
  `ra=999` → 422, unknown `obs_id` → 404. `If-None-Match` → 304. No response carried `fits`.
- IRSA forced unreachable with a dead HTTPS proxy: cached key still `hit`, `?refresh=true` → 200
  `stale`, uncached key → 503 naming the cause.
- In the browser at 1440×900: Barnard live (14 epochs, image rendered, panel reads "not measurable");
  R Draconis with the API stopped (20 committed epochs, still renders).

### Fixed in review ([#10](https://github.com/Moya-Art/ZenithSquad-spherex/pull/10))

Found by using the tool: a cold WISE 0855 load sat on "loading sequence…" with no explanation, and a
failed build was reported as "no sequence committed yet".

- **The wait now says what it is.** `web/src/LoadingNotice.tsx` names the work ("Building Epsilon
  Indi B from the NASA archive"), explains that a first visit downloads one image per observing date
  and renders them against a single stretch, and ticks an elapsed counter so a slow build is
  distinguishable from a hang. The counter lives in its own component, so mounting resets it and no
  effect writes state directly.
- **A failure is reported as itself.** `loadSequence` used to fall back to the committed file and,
  when that file did not exist either, return `null` — which the UI rendered as "no sequence
  committed", blaming a missing file for an archive that never answered. The API's error now
  surfaces with its status and a **Try again** button that re-issues the request.
- **The "missing" message stopped talking about Phase 3.** It named R Draconis D6 as the only
  sequence that existed, which stopped being true when the API landed.

### Notes for the next phase

- Phase 6 replaces the `/cube` stub and nothing else: `pipeline/cube.py` is a new file, and the route
  becomes real without touching the cache or the fallback.
- A Cloud Run cold start begins with an empty disk, so every new container pays one cold `/frames`
  build. Phase 8's bucket is the fix; `API_CACHE_DIR` and `FITS_CACHE_DIR` are already the seams.
- The `404` for a zero-coverage coordinate is exercised by a stubbed archive only: DR1 is all-sky, so
  a real empty patch may not exist to test against.
- `stale: true` needs `band` in the request, because the cache key contains it.
- Phase 7's Photometry for Barnard depends on the `BLOOM` question above.

---

## Phase 3 — Sequence build (R Draconis) — 2026-11-15

### Added

- `pipeline/fits_io.py` — one level-2 cutout: IMAGE minus ZODI in MJy/sr, FLAGS, VARIANCE, celestial
  WCS, and the central wavelength from the `W` WAVETAB WCS. `BUNIT` is checked, not assumed.
- `pipeline/flags.py` — bit names read from the `MSKN*` cards in the FLAGS header, never hardcoded.
  The bad set is the 19 names the official photometry demo uses; `SOURCE` is deliberately not bad,
  because 99.9 % of pixels carry it.
- `pipeline/render.py` — one global percentile stretch; WebP encoder steps quality down until a frame
  fits under 60 KB.
- `pipeline/measure.py` — `centroid_2dg` on a 9×9 box, r = 3 px aperture, sigma-clipped annulus, flux
  in mJy from the pixel area, error from VARIANCE, `sky_offset` in arcseconds.
- `pipeline/sequence.py` — band selection, one frame per date, threaded download with cache,
  reprojection onto the first grid, common-coverage crop, stretch, WebP, manifest.
- `pipeline/cli.py build --target r_dra` — a row per date as it completes.
- `data/fallback/sequence/r_dra_D1.json` and 21 `r_dra_D1_<date>.webp` frames (370–726 bytes each).
- `data/fallback/sequence/r_dra_D6.json` and 20 `r_dra_D6_<date>.webp` frames. D1 is the band the
  plan's rule picks; D6 is built too because `web/src/data.ts` asks for the sequence of the target's
  preview band, and the merged UI would otherwise show "no sequence yet".
- `tests/` — 51 tests, none touching the network; one reads the committed sequence.
- **Deleted `scripts/dev_sequence.py`**, as its own note in the Phase 4 entry asked once
  `pipeline/sequence.py` existed. Two manifest producers is two truths.

### Measured

- R Draconis, `spherex_dr1`, D1: **21 dates**, 67 frames. D1 ties D4 on dates (21) and wins on frames
  (67 against 65), with the sharper PSF.
- One stretch for the sequence: `vmin = 0.024`, `vmax = 3.985` MJy/sr.
- Crop 88×80 px of the 175×176 requested: 13 of the 21 cutouts are clipped by the detector edge.
- `bad_fraction` 0.015–0.106 — believable, and only computable because the mask is per-bit.
- Motion: first-to-last 14.89″ over 0.46 yr, fitted rate `+6.33, +0.93` arcsec/yr with residuals of
  3.82 and 2.21″. `significant: false`, `reliable: false`.
- D6, for the UI: 20 dates, `vmin = −0.035`, `vmax = 7.991`, first-to-last 5.43″ over 0.99 yr, fitted
  rate `+2.07, +0.97` arcsec/yr, also `significant: false`.

### Decisions

- **A sequence frame is a date.** The plan asks for "one WebP per date" and "N frames sharing one
  vmin/vmax"; those only reconcile if the unit is the date. Each date takes its earliest exposure and
  records `frames_available`.
- **Measured on the native grid, reprojected only for display**, because interpolation smooths a PSF
  barely one pixel wide and would bias the centroid.
- **`measure` is null when the core saturates**, rather than a flux with an invented `snr`.
- **The star is excluded from the stretch** (a 12 px disc). Its halo reaches ~30 MJy/sr while the
  field's 99th percentile is 2.8; including it compressed the field into the bottom 9 % of the range
  and produced 0.3 KB frames that showed almost nothing.
- **NaN at the saturated core is filled for display only.** The archive stores NaN on the most
  saturated pixels; reprojecting that put a black hole in the middle of a bright star.
- **Motion is a fitted rate with its scatter**, not an assumed error on first-minus-last. An assumed
  0.5 px turned a 14″ wander into a fake 3-sigma detection; the fit reports no significant motion.

### Plan changes

- **§1.2** — the R Draconis row said "D3 or D6 (20)". Phase 2's committed baseline measures D1 and D4
  at 21 dates, so it now reads "D1 or D4 (21)".
- **§5** — `data/fallback/{target}/` becomes `data/fallback/sequence/`, one `{slug}_{band}.json` plus
  `{slug}_{band}_{date}.webp` frames. `web/src/data.ts` shipped that layout in Phase 4; conforming to
  it beats shipping two layouts that disagree.
- **§6 item 6 (annulus)** — 5–8 px becomes 8–16 px. At 6.15″/px the planned annulus is 30–49″ from the
  centre, which sits inside the target's own wings: measured background 21.8 MJy/sr against a sky of
  0.13. **This one changes the method and needs your approval** — it is not silently adopted.
- **§6 item 6 (fields)** — `x, y, flux, flux_err, snr, bad_fraction, wavelength_um` move under
  `measure`, which is `null` for saturated frames; `saturated`, `bytes` and `frames_available` sit on
  the frame itself.
- **§6 items 3–4 (stretch)** — the global stretch is computed over all frames *excluding a 12 px disc
  around the target*, so a saturated core cannot set `vmax` and flatten the field.
- **§6 done-when (motion)** — `dx_arcsec`/`dy_arcsec` are reported inside `motion` alongside a fitted
  rate, slope error, scatter and a `significant` flag, because arcseconds with an error are not enough
  to tell motion from a wandering centroid.

### Findings that changed the plan

- **R Draconis is saturated in all six bands**: `OVERFLOW` + `BLOOM` on the peak in every detector,
  2 300–6 500 MJy/sr. Epsilon Indi is saturated too; Barnard's Star and RW Aurigae are clean; WISE
  0855 is not detected at all. A quarter of the named targets cannot be photometered by SPHEREx.
- **13 of 21 cutouts arrive clipped** (97×175, 139×97, 176×100 …), which is why the crop is 88×80 and
  why the target can sit at x = 50 in one frame and x = 87 in another. Positions are compared through
  the WCS, never through pixel indices.
- **The cutout SIP coefficients do work.** SIP reproduces the target pixel to ~0.2 px; dropping it
  moves the answer by up to 73″. The astropy warning about SIP is noise here.
- **R Draconis is the wrong target to prove motion on.** Its real motion is 0.02″/yr — 0.003 px. What
  the centroids do is drift with the roll angle of each visit. Barnard's Star is the honest test.

### Verification

- `pytest tests/ -q` → 51 passed.
- A contact sheet of six dates opened and looked at: filled core, visible field stars, target in the
  same place in every tile.
- Every frame under 60 KB, and the manifest's `bytes` matches the files on disk.
- `python -m pipeline.cli build --target r_dra --band D1` reproduces all of the above from the cache.

### Notes for the next phase

- Phase 4 will show **no measure** for every `r_dra` frame, because the star saturates. That is the
  correct rendering, not a missing field; the panel must read `motion.reliable` before saying
  anything about movement.
- `measure.py` has never run against an unsaturated real target. RW Aurigae or Barnard's Star in
  Phase 7 is where `snr` first means something.
- The sequence is 88×80 px because that is the region all 21 visits cover. A smaller request would
  clip less but would not enlarge that intersection.

---

## Phase 4 — The UI, against committed files — 2026-11-15

Merged in [#6](https://github.com/Moya-Art/ZenithSquad-spherex/pull/6). Squash-merged onto `main`.

### Added

- `web/src/BlinkStage.tsx` — every frame decoded into an `ImageBitmap` **before** play is enabled.
  Drawing is a single `drawImage` blit, so nothing between two frames flickers; a flicker would read
  as a real change in the sky. Play stays disabled until the last frame is in memory, and if the
  wanted frame has not decoded yet the nearest decoded one is drawn, so the stage is never blank.
- `web/src/Timeline.tsx` — two tracks on one time axis. **SEEN** puts a mark at each epoch's real
  `t_min`; **FLUX** plots the measured flux against the same x. The alignment is the argument:
  the hole in the coverage is the hole in the science. Playhead and hover share the axis, and the
  SVG is rendered at 1 user unit = 1 CSS pixel (measured with `ResizeObserver`) so labels are not
  distorted and marks do not drift from their dates.
- `web/src/Inspector.tsx` — per-epoch panel. SNR is the dominant number at 32 px because it decides
  whether the frame is worth inspecting; flux, good-pixel fraction and the outlier statistics stay
  as table rows.
- `web/src/PlateContext.tsx` — target-level reading beside the image: variability across the
  sequence, centroid motion, catalogue position. Kept separate from the inspector so a single noisy
  frame can never read as a finding.
- `web/src/data.ts`, `web/src/viewState.ts`, `web/src/captions.ts` — typed access to
  `data/fallback/sequence/`, URL state (`?target=&band=&epoch=`, with `epoch` a **date** rather than
  an index so a pasted link keeps its meaning when the frame list changes), and one plain-language
  sentence per target.
- `web/vite.config.ts` — a dev middleware and a build step that serve `../data` at `/data/*`.
  Nothing in the app knows it is reading committed files, so Phase 5 swaps the loaders only.
- `web/src/tokens.css` — colour and type tokens, so a palette change does not touch component CSS.
- `web/public/space-apps-logo.png` — the NASA Space Apps lockup, white artwork on transparency, in
  the top-left of the chrome.

### Changed

- `web/src/App.css` rewritten as a workbench rather than a centred stack: targets rail, plate
  (image beside its reading), inspector column, timeline as a real panel instead of a footer strip.
- `web/src/App.tsx` holds the state machine only — loading, missing, error, ready — and the
  keyboard map (`Space` play/pause, `←`/`→` step).
- The image is capped by viewport height (`min(100%, 58vh, 560px)`) so it can never push the light
  curve off-screen, and the timeline's `H_AXIS` is deeper than the year baseline so the year label
  under a month tick is not clipped by the viewBox.

### Removed

- The Vite template's `src/assets/hero.png`, `react.svg`, `vite.svg` and `public/icons.svg`, and the
  template CSS. None of it survived the first real screen.

### Added — development bridge, not a deliverable

- `scripts/dev_sequence.py` — Phase 4 needs a multi-epoch sequence to blink, and Phase 3
  (`pipeline/sequence.py`) has not landed. This produces the smallest honest stand-in: SIA search →
  cutout → common grid → one global stretch → aperture flux, SNR and centroid per frame. It states
  its own gaps in its docstring (approximate photometry, no `SigmaClip`, sequential, PNG not WebP)
  and is meant to be deleted when Phase 3 lands. The manifest shape is a subset of Phase 3's, so the
  UI should not need rewriting.
- `data/fallback/sequence/r_dra_D6.json` plus ten frames — R Draconis, D6, 0.2° field at 6.15″/px,
  ten epochs spanning 0.989 yr.

### Decisions

- **A shared stretch is not negotiable.** All ten frames use `vmin = -0.0274`, `vmax = 91.76`
  MJy/sr from the manifest. Per-frame autoscaling would make every epoch look equally bright and
  destroy the only signal the sequence carries.
- **Gaps stay gaps.** The marks sit at real `t_min`, and the 197-day and 111-day holes are visible
  as holes. Evenly spaced dots would be a lie about the coverage.
- **Motion is reported as consistent with zero.** The first and last centroids differ by 5.81″ over
  0.99 yr, which looks like a detection until the error is read: the fitted rate is
  (−3.32, −3.08) ± (0.94, 2.03) ″/yr and the centroid wanders by (1.02, 2.22)″. R Draconis pulsates;
  it does not move. The UI says "consistent with zero" and explains why.
- **The URL carries a date, not an index**, so a shared link survives the frame list changing.

### Plan changes

Reason for all of them: Phase 4 names a UI for a sequence that Phase 3 has not built, and two of its
specified panels assume quantities the committed data does not carry.

- **Phase 4, "Time strip".** Said a strip of dates at their real `t_min`. Now a two-track timeline:
  coverage above, measured flux below, sharing one axis. A strip of dates alone answered "when did we
  look" but left "what changed" to a number in a panel; the whole point of the tool is the two
  together, and the alignment is what shows the gaps are the gaps in the science.
- **Phase 4, "Measurement panel".** Said `"Moved 0.8″ ± 0.3″ over 1.02 years", always visible`. The
  measured value is **not** significant (5.81″ over 0.99 yr, but (−3.32, −3.08) ± (0.94, 2.03) ″/yr
  against (1.02, 2.22)″ of wander), so printing a bare "moved" figure would assert a detection that
  is not there. Now the panel states "consistent with zero" and shows the fit and the scatter that
  justify it. The rule stands — the motion verdict is always visible — but it must not overstate.
- **Phase 4, "Outlier strip".** Said a strip. Kept as rows in the epoch inspector instead: mean,
  median and max-abs change describe one frame, not a series, so they belong with the rest of the
  per-frame numbers rather than in a third timeline-like element competing for the same axis.
- **Phase 4, "URL state".** Said `/view?ra=&dec=&band=&epoch=&fov=`. Now
  `/view?target=&band=&epoch=`: the committed build identifies a sequence by target slug, and
  arbitrary coordinates need the Phase 5 API. `epoch` is a date, not an index, so a pasted link keeps
  its meaning when the frame list changes. `fov` is dropped until Phase 5 can serve a second field size.
- **Phase 3, `scripts/dev_sequence.py`.** Phase 3 owns the sequence builder and has not landed, so
  Phase 4 could not be built against real multi-epoch data. A development bridge was added and is
  declared in its own docstring as not a deliverable, with an expiry: delete it when
  `pipeline/sequence.py` lands. Its manifest is a deliberate subset of Phase 3's so the UI does not
  need rewriting.

### Verification

- `npm run build` → clean, 25 modules, 237 kB JS / 74 kB gzipped.
- `npm run lint` → 0 errors, 2 warnings (both `set-state-in-effect` on effects that synchronise with
  an external fetch, which is the correct use of an effect).
- Ten epochs render and blink with no white flash; the timeline shows the 197-day and 111-day gaps
  at their real positions.
- Flux ranges 9 954 → 24 143 MJy/sr (2.43×) across the sequence, SNR 71.9 → 689.2, bad pixels
  ≈ 0.1% — so the brightness change is in the data, not the display.
- Layout checked at 1440 px and 700 px by screenshot, and the DOM measured (`scrollWidth` equals
  `clientWidth` at both widths, so nothing overflows).

### Notes for the next phase

- **Delete `scripts/dev_sequence.py` when `pipeline/sequence.py` lands.** It is a bridge with a
  stated expiry, and its manifest is a subset of the real one by design.
- Chrome's headless `--window-size` clamps the viewport to a 500 px minimum; screenshots below that
  measure 500 px. Do not trust a "390 px" capture as evidence of the narrow layout — measure the DOM.
- Phase 5 replaces `loadSequence`/`loadTargets`/`frameUrl` in `web/src/data.ts` and the Vite data
  middleware. No component should need to change.

---

## Phase 2 — Timeline pipeline — 2026-11-15

Merged in [#4](https://github.com/Moya-Art/ZenithSquad-spherex/pull/4). Squash-merged onto `main`.

### Added

- `pipeline/catalog.py` — the data layer. One SIA request per target per collection at a fixed
  radius, 4 retries with 10→80 s backoff, VOTable parsing, MJD→date, 30-day epoch grouping, and a
  per-band summary. Standard library only: no astroquery, no FITS.
- `pipeline/cli.py` — `python -m pipeline.cli timeline --all` prints frames / obs / dates / span /
  radius / epochs / longest gap, then per-epoch detail; `--json` gives the shape Phase 3 and Phase 5
  extend. `--radius` and `--epoch-gap-days` are exposed on purpose.
- `scripts/verify_counts.py` — measures BUILD_PLAN §1 and diffs it against the committed baseline
  (counts, per-band numbers, radius), printing `PASS` / `DRIFT` / `UNKNOWN` and exiting 0 / 1 / 2.
  `--update` accepts today's measurement as the new baseline.
- `data/baseline/counts.json` — all ten target-collection rows with per-band counts and the radius
  that answered.
- `tests/` — 22 tests, none of which touch the network.

### Decisions

- **An epoch is a 30-day window.** Dates within 30 days of the previous date share an epoch; the
  blink still steps through individual dates. One constant, one flag, and the gap list is printed on
  every run so the choice stays visible.
- **Zero rows is a result.** WISE 0855 has 0 frames in `spherex_qr3` and that is a correct answer.
  Only an archive that never answers is an error (`UNKNOWN`, exit 2).
- **A committed baseline, not an eyeball comparison.** Drift is expected (the archive ingests
  weekly), so it is printed per field — `frames 261/258 (+3)` — rather than silently absorbed.

### Findings that changed the plan

- **IRSA's CSV output is not valid CSV.** `s_region` is written as `POLYGON ICRS r d,r d,…` with
  unquoted commas, so the 51-column header meets 53 values on every data row and every field after
  `s_region` shifts left. Parsing moved to VOTable (`xml.etree`), and a test pins a cell containing
  exactly that polygon. BUILD_PLAN §1.3 and §2 now record the defect.
- **The planned radius fallback changed the answer.** 0.001° → 0.01° on failure was measured to give
  R Draconis 413 frames against 422, and Epsilon Indi QR3 116 against 117. A count that depends on
  which retry succeeded is not a measurement, so the radius is now fixed, recorded in the baseline,
  and a 502 surfaces as `UNKNOWN`.
- **Counts drift within a day.** WISE 0855 was 258 frames when BUILD_PLAN §1 was measured and 261
  that evening. The plan's table now comes from this tool, not from a hand count.
- **Epsilon Indi QR3 at 0.001° answers intermittently** (502 in the morning, 116 rows in the evening,
  502 again an hour later) while 0.01° answered throughout.

### Plan changes

Reason for all of them: the plan described a method that measurement showed to be broken.

- **§1 intro.** Said the numbers were hand-counted on 2026-11-15. Now says they come from
  `verify_counts.py` against `data/baseline/counts.json`, and names the two things that move them
  (weekly ingestion, search radius).
- **§1.1 table.** WISE 0855 `spherex_dr1`: 258 / 129 / 27 → **261 / 131 / 28** (the archive ingested
  three frames during the measurement day). Epsilon Indi `spherex_qr3`: 117 / — / 10 → **116 / 58 /
  10**, now measured at 0.001° rather than 0.01°.
- **§1.3 table.** The row saying "SIA answers a plain GET with `RESPONSEFORMAT=csv`" was true but
  misleading: it said nothing about the CSV being malformed. Replaced with the VOTable row plus a new
  row recording the unquoted-comma defect. The radius row now records that 0.001° answers
  intermittently for Epsilon Indi QR3.
- **§2 query form.** `RESPONSEFORMAT=csv` → `RESPONSEFORMAT=votable`, and the script's job changed
  from "re-derives §1" to "measures §1 and diffs it against the baseline".
- **§2 rules.** New rule: parse VOTable, not CSV. The old "Epsilon Indi QR3 needed `radius=0.01`"
  bullet was replaced by "one fixed radius, never an adaptive one", because the fallback was measured
  to change the counts.

### Verification

- `pytest tests/ -q` → 22 passed, no network.
- `python3 scripts/verify_counts.py` → 10 PASS against the baseline it wrote. Later passes reported
  `UNKNOWN` for whichever rows IRSA dropped, with exit 2 and a named cause — never a zero.
- `python -m pipeline.cli timeline --all` → R Draconis: 3 epochs, longest gap 99 d. WISE 0855:
  3 epochs, longest gap 178 d. Epsilon Indi QR3: 1 epoch, no gap over 7 d.

### Notes for the next phase

- Phase 3 should reuse `catalog.search_epochs` for band selection, and leave `data/fallback/preview/`
  where it is: the `data/fallback/{target}/` layout is Phase 3's migration, not Phase 2's.
- The CLI builds its whole table before printing, so a killed run shows nothing. Printing per row as
  it arrives is a five-line fix whenever someone is next in that file.
- Do not add a cache in `catalog.py`: `verify_counts.py` must ask the live archive, and a cached row
  list would hide the drift it exists to detect. Phase 5 owns caching.

---

## Phase 1 — Target previews — 2026-11-15

Merged in [#2](https://github.com/Moya-Art/ZenithSquad-spherex/pull/2). Commit `c023ac7`.

### Added

- `data/targets.json` — the five targets with their slug, name, RA/Dec, preview band, proper motion
  and the catalogue that proper motion came from. This is the file the UI reads; nothing else needs
  the coordinates hardcoded.
- `scripts/preview_targets.py` — SIA query → most recent `spherex_dr1` row in that target's band →
  cutout → `IMAGE - ZODI` → percentile stretch → PNG. Reads extensions by name, asserts `BUNIT` is
  `MJy/sr`, retries 5× with 10→80 s backoff, caches FITS under `data/cache/` (gitignored).
- Five previews in `data/fallback/preview/`, named `<slug>_<band>.png`: `r_dra_D6`, `wise0855_D5`,
  `barnard_D6`, `eps_ind_D6`, `rw_aur_D6`.

### Decisions

- **Cutouts are centred on the epoch-corrected position, not the J2000 coordinate.** The challenge
  coordinates are J2000 and the frames are 2026, so proper motion was propagated to each exposure's
  epoch. Barnard's Star moves 273.8″, Epsilon Indi 124.0″, WISE 0855 214.9″, R Dra 0.6″, RW Aur
  0.7″. Reading the raw J2000 pixel gave empty sky for the first two (0.18 and 0.38 MJy/sr) where the
  stars actually hold 1,205 and 4,649. Any future aperture, marker or photometry must do the same.
- **Band is per target**: D6 for R Dra, Barnard, Epsilon Indi and RW Aur; D5 for WISE 0855.
- **Cutout size 0.3°** (≈175 px at 6.15″/px), overridable with `--size`.
- **Stretch is 1–99.5 percentile over finite pixels, once per image**, written into the PNG. Phase 3
  replaces this with one global `vmin`/`vmax` per sequence; per-frame autoscale is never acceptable.
- **Failure modes stay distinct**: exit code 2 when the archive never answers (502/504/timeout),
  exit code 3 when the position genuinely has no rows in that band. A flaky proxy must never read as
  an empty sky.

### Findings that changed the plan

- **WISE 0855 is a depth problem, not a band problem.** Simbad gives J = 25.00; against the measured
  single-frame noise (σ = 0.0457 MJy/sr) that is 0.0016σ, 8.7 mag below a 5σ detection. No band
  reaches it — only the all-sky cube has a chance. Its preview is an honest star field with no
  visible target.
- **WISE 0855's challenge coordinate is not J2000.** 08h55m10.83s −07°14′42.5″ is the 2010/2011
  discovery position; the J2000 position is 133.818908 −7.247047, 86″ away. `targets.json` stores
  the J2000 position, the proper motion, and a `coordinate_note` recording the difference.
- **Archive counts drift.** WISE 0855 returned 258 rows when the build plan was measured and 261
  later the same day. Counts quoted from here on come from `verify_counts.py` (Phase 2).

### Plan changes

Recorded after the fact, from the edits made in this phase.

- **§9 open items.** "WISE 0855 is visible only at the long-wavelength end" was replaced by the
  measured depth limit (J = 25, 0.0016σ, 8.7 mag below a 5σ single-frame detection). Added that the
  challenge coordinate is the 2010/11 discovery position, not J2000, and that every coordinate in the
  document is J2000 while every frame is 2025–2026.
- **§4 data rules.** New rule: propagate proper motion to the exposure epoch before pointing anything
  (Barnard 273.8″, Epsilon Indi 124.0″), with the empty-sky numbers that convinced us.
- **§5 targets table.** WISE 0855's row now shows its J2000 position (133.818908, −7.247047) rather
  than the discovery coordinate, with the 86″ difference explained.
- **§1.** Notes that archive counts drift, so quoted numbers come from the tool rather than the table.
- **Phase 1, Phase 7, Phase 11, §7 checklist.** Corrected so they stop promising something
  impossible: WISE 0855 ships as cube spectrum + RGB composite with a labelled non-detection, four
  targets blink, and co-adds are described as worth √N rather than as the answer to an 8.7 mag gap.

### Verification

- `python scripts/preview_targets.py` → five PNGs, exit 0; all five opened and inspected by hand.
- Peak within 3 px of centre: R Dra 5,548 · RW Aur 702 · Barnard 1,205 · Epsilon Indi 4,649 MJy/sr.
  WISE 0855: 0.48 against noise 0.046, i.e. nothing — as predicted above.
- Row counts matched the plan exactly for four targets (413 / 240 / 344 / 226); WISE 0855 drifted as
  noted.
- IRSA returned 502 on most requests during the run; repeated whole-script runs got all five through.

### Notes for the next phase

- **There is one frame per target, not a sequence.** No blink, no time strip, no manifest, no
  measurements yet — those arrive in Phase 3. The UI can be built against the previews, but a real
  blink needs the sequence build.
- `data/cache/` holds ~22 MB of downloaded FITS and is gitignored; deleting it only costs re-downloads.
- The Barnard D6 frame contains a straight diagonal streak across the cutout — consistent with a
  satellite trail. Useful to remember when a "moving object" shows up in a difference image.

---

## Phase 0 — Environment — 2026-11-15

Merged in [#1](https://github.com/Moya-Art/ZenithSquad-spherex/pull/1). Commit `9318684`.

### Added

- Repository initialized, with `main` established as the base branch.
- `requirements.txt` — 83 pinned dependencies, frozen from **Python 3.14.7**. Every package
  resolved to a binary wheel, so the environment installs without compiling anything: `numpy`,
  `astropy`, `astroquery`, `reproject`, `photutils`, `pillow`, `hpgeom`, `google-cloud-storage`,
  plus `fastapi` and `uvicorn[standard]` (Phase 5) and `pytest` (§7 verification gates).
- `web/` — frontend scaffolded with `create-vite`: Vite 8.3.6, React 19.3.1, TypeScript.
  `npm run build` passes.
- `.gitignore` — `.venv/`, `__pycache__/`, `*.py[cod]`, `node_modules/`, `dist/`, `data/cache/`,
  `.env`, `.env.*`, `.DS_Store`.
- `README.md` — what the tool is, the five target coordinates, how to run both halves, and
  references with the DR1 dataset DOIs (`10.26131/IRSA678` spectral images,
  `10.26131/IRSA679` all-sky cube).

### Notes

- Both halves verified runnable from a fresh clone: `pip install -r requirements.txt` then
  `npm ci && npm run build`, with nothing needed from outside the repository.
- No project code, data, or documents were added in this phase — the first content arrives in
  Phase 1.
- Deployment (Vercel, Cloud Run, GCS, DNS) is deliberately deferred to Phase 8.
