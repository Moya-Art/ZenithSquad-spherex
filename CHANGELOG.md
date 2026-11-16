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

## Phase 7d — the plate opens on committed frames, and the URL becomes a place — 2026-11-16

Merged in [#20](https://github.com/Moya-Art/ZenithSquad-spherex/pull/20). Squash-merged onto `main`.

### Fixed
- The date plate asked the API first, so a cold `/frames` held an empty plate for 37 s while the target's frames sat committed in the repository. A named target now opens on `data/fallback/sequence/<slug>_<band>.json` at once, marked `stale`, and the live request replaces it in place if it answers. A coordinate with no committed artifact keeps the live path and its progress notice, which is the distinction the plate now makes visible.
- The first request could leave without a fallback at all: `useCoordinate` had no target until `/targets` arrived. The plate waits for that answer.
- **Back did nothing.** `writeViewState` used `replaceState` while `useCoordinate` listened for `popstate` "so Back returns to the previous coordinate" — with `replaceState` no history entry is ever created, so that could never happen. Navigation pushes now; correcting the bar replaces.
- The address bar could contradict the screen: an empty URL left no coordinate in it, and `?ra=999` survived reloads and shares. `canonicalViewState` fills in the default, normalizes precision, or strips a coordinate that was never valid.
- `parseViewState` rounds to five decimals before the range check, so `359.999996` is rejected instead of being sent as `360.00000`, and the position the loaders use is the one the link states.

### Added
- `loadCommittedSequence`, the mirror of `loadCommittedCube`, plus five `canonicalViewState` cases (20 frontend tests total).

### Plan changes
- §2.4 wrote the loading policy as "live first, committed files as the net". For a named target it is now committed first with the live build replacing it; an arbitrary coordinate is still live first, because it has nothing to fall back on.
- `/healthz` is `/health` — see Phase 7c.

---

## Phase 7c — the health route — 2026-11-16

Merged in [#19](https://github.com/Moya-Art/ZenithSquad-spherex/pull/19). Squash-merged onto `main`.

### Fixed
- `/healthz` never reached the API on Cloud Run: Google's frontend answers that path itself, before the container. Confirmed from outside — `/healthz` returns an HTML `404 … That's all we know.` with no `x-cloud-trace-context`, while a path FastAPI does not serve returns its own JSON 404 with the header. The route is now `/health`, same body. Nothing referenced the old name, and no alias is left behind.

### Plan changes
- The Phase 8 gate written as "done when `/healthz` reports the bucket" now reads `/health`. It could never have been observed at the old path on Cloud Run.

---

## Phase 7b — the frontend shell, joined to `main` — 2026-11-16

Merged in [#18](https://github.com/Moya-Art/ZenithSquad-spherex/pull/18). Squash-merged onto `main`.

### Added
- One page, two plates. A navbar with a coordinate field per axis, Targets and Queue pop-overs; a scrolling epoch and palette sidebar; a read-only track stack; a footer. The Time/Spectrum modes and the left rail are gone.
- `web/src/viewState.ts` carries the coordinate and nothing else: `?ra=&dec=` at five decimals — the rounding the cache key already uses — so a shared link and the request it triggers always name the same entry. A missing, half or out-of-range coordinate is rejected before any request is made.
- `web/src/resolveTarget.ts`: a coordinate within `1e-4°` (≈0.36″) of a named target resolves to it. That is what lets a coordinate-only URL fall back to the committed artifact, and it is tight enough that no two of the five targets can be confused.
- `vitest`, with 15 tests over `viewState` and `resolveTarget`.

### Changed
- The greyscale decoder and the palette canvas are shared by both plates. Every frame is recoloured offscreen before play is enabled, so the blink does not flicker. Turbo leaves the palette list; the RGB composite takes its slot and affects only the wavelength plate.
- The wavelength plate loads on demand unless a committed cube exists, so opening the page never queues a 306 MiB build by itself.

### Fixed
- `/queue` had been written twice — here and in #14. The merge keeps `main`'s: one route, one `queue_state()`, one set of progress records carrying the coordinate. The branch's duplicate is removed, and its two assertions (a listing carries neither `planes` nor `points`; the name comes off the progress record) move into `main`'s suite.

### Plan changes
- §1.4 assigned the queue endpoint to the frontend half of gate B. #14 shipped it first, so the frontend's own implementation was dropped rather than merged. Nothing else in the plan moved.

---

## Phase 8c — the bucket: durable cache — 2026-11-16

Merged in [#21](https://github.com/Moya-Art/ZenithSquad-spherex/pull/21). Squash-merged onto `main`.
Cloud Run revision `spherex-api-00004-vcv`, `APP_VERSION` 0.8.0.

### Added

- `api/app/store.py` — `LocalStore`, `GcsStore`, `default_store()`. The store sits *behind* `Cache`,
  not beside it: object names are the path relative to the cache root, so there is one naming rule
  (`seq/<key>/manifest.json`, `cubes/<key>/cube/plane_007.webp`, `frames/<key>.webp`) and no second
  layout to keep in step. With `GCS_BUCKET` unset the store is a no-op, which is what local development
  and the test suite run on.
- `Cache.ensure_local()`, `Cache.publish_sequence()`, `Cache.publish_cube()`; read-through on
  `manifest`, `frame`, `cube_manifest` and `progress`.
- Bucket `gs://zenith-squad-2026-artifacts` (us-central1, private, uniform bucket-level access) and a
  dedicated service account `spherex-api@zenith-squad-2026.iam.gserviceaccount.com` with
  `roles/storage.objectAdmin` **on that bucket only**. Cloud Run now runs as it (`--service-account`
  in `scripts/deploy_api.sh`) instead of the Compute Engine default account.
- `tests/test_store.py` — 9 tests against a fake client; read-through across two cache roots, a failed
  upload that must not fail the request, progress throttling, and a plane served after the instance
  that built it is gone. 158 tests total, all green with `GCS_BUCKET` unset.

### Fixed

- `GcsStore.ping()` used `bucket.reload()`, which needs `storage.buckets.get` — a permission
  `objectAdmin` does not carry, because it is scoped to objects. On the deployed service this reported
  `bucket_reachable: false` for a bucket that had just accepted 22 objects. It now probes with a
  one-object listing (`storage.objects.list`, inside the role), and a test pins the distinction.

### Measured

| What | Before | After |
|---|---|---|
| `/frames?target=wise0855&band=D5`, cold | 1 m 06 s | — (published once) |
| Same request on a **new revision** (empty `/tmp`) | 1 m 06 s | **0,5 s**, `x-cache: hit` |
| `/cube?ra=133.9&dec=-7.3`, cold | ~90 s (plan estimate) | **11 s**, 109 objects published |
| Same cube after a forced restart | full rebuild | 1,4 s `ready/hit`, plane 0,55 s, composite 0,50 s |

The 11 s is the interesting number: the plan estimated ~90 s for a cold cube from the local
measurement, but S3→Cloud Run moves the 306 MiB tile far faster than a home connection does, so a
cold cube in production is cheap. `/health` now reports `bucket_reachable: true`.

Cold sequence builds in the cloud, one per target, pre-warmed into the bucket so the first visitor
never pays them: `r_dra` D6 100 s, `barnard` D6 40 s, `eps_ind` D6 103 s, `rw_aur` D6 36 s. All under
the 600 s request timeout, with `eps_ind` the closest to it.

### Plan changes

- **Object naming.** `BUILD_PLAN.md` §Phase 8 asks for `previews/ cube/ manifests/ tiles/ cache/`. The
  bucket instead mirrors the local cache tree (`seq/`, `frames/`, `cubes/`), because that tree is what
  the pipeline writes into: one name per object beats a translation table between two layouts.
- **Tiles are not in the bucket** (decision taken before the work). They are ingredients, they are
  deleted after a build, and a rendered cube makes a rebuild rare. The plan's `tiles/` prefix is
  therefore not used.
- **The cold-cube estimate above was wrong** and is corrected here rather than left in the doc.

### Still open

Bucket, deployment and refresh are now three of six Phase 8 items. Unbuilt: `jobs/refresh.py`, Cloud
Scheduler, `POST /refresh`.

---

## Phase 8a — the other four targets, prebuilt — 2026-11-16

Merged in [#16](https://github.com/Moya-Art/ZenithSquad-spherex/pull/16). Squash-merged onto `main`.

### Added

- `data/fallback/cube/{wise0855,barnard,eps_ind,rw_aur}.*` — 102 planes, one composite and one
  `cube.json` per target. Until now only `r_dra` had a committed cube, so four of the five targets
  could not open a spectrum without a 306 MiB download on first view.
- `data/fallback/sequence/*` for the same four targets, in **two bands each**: the band with the most
  dates (the one the API picks when a request omits `--band`) and the band `targets.json` names (the
  one the frontend asks for by default, `App.tsx::effectiveBand`). Without the second one, the
  frontend's own fallback path misses exactly when it is needed — when the API is not answering.

### Measured

- Cube builds, one tile (320 909 760 B) per target: `wise0855` 91 s, `barnard` 88 s, `eps_ind` 99 s,
  `rw_aur` 15 s (tile already cached). Rendered output ~740 KB per cube.
- Sequence builds: `wise0855` D2/D5, `barnard` D3/D6, `eps_ind` D2/D6, `rw_aur` D3/D6.
- `cache purge --raw --tiles --keep 0`: **1.78 GB freed** (496.7 MB of cutouts, 1.28 GB of tiles),
  `data/cache` 1.7 GB → 7.3 MB. Nothing was committed from it: the tiles are ingredients.

---

## Phase 8b — the API deployed to Cloud Run — 2026-11-16

Merged in [#17](https://github.com/Moya-Art/ZenithSquad-spherex/pull/17). Squash-merged onto `main`.

This is a **partial** Phase 8: deployment only. The bucket, `jobs/refresh.py`, Cloud Scheduler and
`POST /refresh` are still open, so `/healthz` still reports `bucket_reachable: null` and the cache
lives on the instance.

### Added

- `scripts/deploy_api.sh` — build + deploy in one command, image tagged with `git rev-parse --short
  HEAD` so a revision is traceable to a commit. Cloud Run moves traffic to a new revision only once it
  is healthy, and the previous revision stays for `update-traffic`.
- `scripts/cloudbuild.yaml` — four lines, because `gcloud builds submit --tag` only accepts a
  `Dockerfile` at the context root and this one lives in `api/`.
- `scripts/api.env.yaml` — the runtime environment, deployed with `--env-vars-file`. `--set-env-vars`
  cannot express `CORS_ORIGINS`: gcloud splits the value on commas and then parses each piece as its
  own `KEY=VALUE`, which fails on `https://…`.
- Cloud Run service `spherex-api` in `us-central1`, project `zenith-squad-2026` (new project, billing
  linked, APIs enabled), image in Artifact Registry `us-central1-docker.pkg.dev/zenith-squad-2026/api`.

### Changed

- `api/Dockerfile` copies `data/fallback/cube`. Without it the container holds `targets.json` but no
  committed cubes, and `service.committed_cube` silently finds nothing — every target would fall
  through to a live build and the Phase 8a work would be invisible in production.

### Decided (each one is a deployment fact, not a preference)

- `--no-cpu-throttling`. The cube builder is a background thread and the request that starts a build
  returns `202` immediately; with CPU throttling on, the build only advances while a request is being
  handled and stalls between polls.
- `--max-instances 1`. The cache is per-instance disk; two instances means two caches, a doubled
  306 MiB download, and `/queue` answering differently depending on which instance replies.
- `--min-instances 0`. Always-allocated CPU is billed while an instance exists; with a 0 minimum the
  instance is created by the first visitor and lives ~15 min after the last request.
- `--memory 4Gi`, not the build plan's `2Gi`. `/tmp` on Cloud Run is memory-backed, so the 306 MiB
  tile lives in RAM alongside the `512×512×102` numpy window and its per-plane copies.

### Measured

- `gcloud builds submit`: 1 m 57 s, image 2.8 MiB of source context, no tiles or `node_modules`
  uploaded (`.gitignore` is used as `.gcloudignore`).
- `/healthz` → **unreachable** (see Plan changes).
- `/targets` → five slugs. `/cube?target=wise0855` → `state: ready`, served from the committed
  artifact, proving the `COPY` above.
- `/frames?target=wise0855&band=D5`, cold: **37 s**, under the 600 s timeout.
- CORS preflight from `https://www.zenithsquad.earth` → `200` with
  `access-control-allow-origin: https://www.zenithsquad.earth`.
- `pytest` → 141 passed.

### Plan changes

- **`/healthz` cannot be observed on Cloud Run.** The path is intercepted by Google's frontend before
  the container: it answers an HTML 404 with no `x-cloud-trace-context`, while a genuine FastAPI 404
  (`/nope`) returns `{"detail":"Not Found"}` with the trace header. Phase 8's "done when `/healthz`
  reports `bucket_reachable: true`" therefore has to be checked on another path once the bucket lands;
  the route itself is unchanged and still correct in local development.
- **Runtime environment moved to `scripts/api.env.yaml`** (§ above).
- **Phase 8 memory 2Gi → 4Gi** (§ above).

---

## Phase 7 corrections, backend C — delete the raw downloads — 2026-11-16

Merged in [#15](https://github.com/Moya-Art/ZenithSquad-spherex/pull/15). Squash-merged onto `main`.

### Added

- `pipeline/cleanup.py` — `delete_raw(paths) -> int`. Explicit paths only (a glob would delete another
  build's inputs) and raw suffixes only (`.fits`/`.fit`/`.part`), so a mistaken list cannot take a
  WebP, a manifest or a `progress.json` with it. A missing file is not an error; a failed unlink is
  skipped rather than turned into a build failure.
- `python -m pipeline.cli cache purge --raw --tiles --keep N` — the hand cleanup for what is already on
  disk, printing bytes freed per group and a total. `--raw` is non-recursive on `data/cache`, so the
  tile directory and the API cache stay separate questions. Neither flag is a usage error (exit 3).
- `tests/test_cleanup.py` — 6 tests: bytes counted, missing file tolerated, non-raw refused, `.part`
  accepted, duplicates counted once, a directory skipped.

### Changed

- `pipeline/sequence.py` and `pipeline/cube.py` report the paths they actually downloaded through a
  `raw_paths` list. It is filled in, not returned: the builder has no business deciding whether its
  ingredients are still wanted.
- `api/app/service.py` deletes them after a successful build — after the manifest and the WebPs are on
  disk, never on a failure (debugging an archive failure needs the file that failed). The cube's final
  `progress.json` records `bytes_freed`.
- `api/app/main.py` configures logging at `LOG_LEVEL` (default `INFO`). Uvicorn sets up its own loggers
  and leaves the root alone, so the freed-bytes record was being written to a logger nobody reads.
- `APP_VERSION` 0.6.0 → 0.7.0.

### Measured

- Live `/frames?target=r_dra&band=D1`: `X-Cache: miss`, 21 dates, `data/cache/*.fits` **333 → 312**,
  second request `X-Cache: hit`.
- Live `/frames?target=r_dra&band=D6`: `freed 88 208 640 bytes of raw downloads` (20 cutouts),
  **312 → 292** files.
- `cache purge --keep 1` on throwaway files: cutouts gone, newest tile kept, `manifest.json`,
  `progress.json` and `data/cache/api/` untouched.

### Result of the one-off purge

`python -m pipeline.cli cache purge --raw --tiles --keep 1` on the working copy:

- cutouts: **292 files, 1.29 GB freed**
- tiles: **5 files, 1.60 GB freed**
- total: **2.90 GB freed**, `data/cache` **3.1 GB → 314 MB**

The kept tile is `hips_20261026_N5_277.fits` (the most recently modified, RW Aurigae's). The five
targets are still answerable without it: `r_dra` from the committed artifact and the other four from
the API cube cache (7.2 MB, untouched). Every artefact under `data/fallback/` is untouched.

### Plan changes

- §5 repository tree gains `pipeline/cleanup.py`; §6 Phase 5 route table gains `GET /queue`; §6 Phase 6
  gains item 7, "delete the tile once the planes exist".
- `Docs/phase-7-corrections.md` §3.2 says every downloader returns its paths. They report them into a
  `raw_paths` list instead — one signature change fewer for the CLI, which must keep its ingredients.
- `Docs/phase-7-corrections.md` §3.1 lists `delete_raw` with no suffix guard. It refuses anything that
  is not raw, which is the cheapest way to make "delete raw" mean exactly that.

---

## Phase 7 corrections, backend B — `GET /queue` — 2026-11-16

Merged in [#14](https://github.com/Moya-Art/ZenithSquad-spherex/pull/14). Squash-merged onto `main`.

### Added

- `GET /queue` → `{"jobs": [...]}`, `Cache-Control: no-store`. It answers the question the page could
  not ask: *is the build I started still running?* The job registry was already on disk (one
  `progress.json` per cache key, from Phase 6), so this is a directory walk and no new storage.
- `api/app/service.py::queue_state()` — newest first; finished jobs are dropped (a done job is a cache
  hit, not a queue item); a stamp older than the 120 s staleness window is a dead worker and is
  dropped; a half-written file is skipped rather than turned into a 500.
- `tests/test_api_queue.py` — 12 tests: empty cache, building, queued, failed, newest-first, finished
  dropped, stale dropped, missing position skipped, corrupt file skipped, name fallback, route shape
  and `no-store`.

### Changed

- A `progress.json` record now also carries `ra`, `dec` and `name`, in every state — queued, building,
  done and failed. Without them the queue could not name a job: the cache key is a hash, and the
  position was never written down.
- `_record_failure` takes the `PositionSpec` so the failed record has it too.

### Measured

- Live check on the R Draconis coordinate: `/cube?ra=248.16775&dec=66.75497` → `202`; `/queue` listed
  it as `building` with `planes_total = 102`; the build reached `done` (102 planes, tile already
  cached) and `/queue` went back to `{"jobs": []}` while the same URL answered `200` from the cache.

### Plan changes

- `Docs/phase-7-corrections.md` §1.4 said the queue should return a list. It returns
  `{"jobs": [...]}`, matching `/targets` returning `{"targets": [...]}`; the frontend reads `.jobs`.
- `Docs/phase-7-corrections.md` §1.4 does not mention `ra`/`dec`/`name` in `progress.json`. They are
  needed, and are the only change to that file's schema.
- §6 Phase 5 route table gains `GET /queue`.

---

## Phase 7 corrections, backend A — one contrast curve — 2026-11-16

Merged in [#13](https://github.com/Moya-Art/ZenithSquad-spherex/pull/13). Squash-merged onto `main`.

### Changed

- `pipeline/render.py` gains `to_uint8_asinh`, moved verbatim out of `pipeline/cube.py`. The cube
  imports it and its local copy is gone, so there is one curve and the date plate and the wavelength
  plate cannot drift apart. `to_uint8` stays: `scripts/preview_targets.py` still uses the linear clip
  for the Phase 1 preview PNGs, which are not the app.
- `pipeline/sequence.py` renders its frames with `asinh`. The stretch is untouched — still global over
  the sequence, still excluding the 12 px target disc — and `measure.py` reads the native image, so
  motion, flux and SNR are numerically identical. Only the PNG/WebP pixels change.
- `api/app/cache.py` gains `RENDER_VERSION = 2`, part of `sequence_key`, `cube_key` **and**
  `frame_key`. Old entries become unreachable rather than being served with the old contrast. The
  ~6.2 MB already under `data/cache/api` is orphaned; nothing reads it again.
- `data/fallback/sequence/r_dra_{D1,D6}` — 41 frames rebuilt with the new curve.

### Measured

- r_dra D1: 21 dates, `vmin = 0.024220` `vmax = 3.985226` MJy/sr before and after — the stretch did
  not move. Frame bytes 12,162 → 12,676.
- r_dra D6: 20 dates, `vmin = -0.034568` `vmax = 7.990590`, 16,152 → 16,908 B. Every frame still
  ≤ 60 KB.
- One D1 frame, 88 × 80 px: mean 48.0 → 51.2 (0–255), p10 8 → 9. The faint field lifts, the bright end
  compresses — the reason for the change.

### Plan changes

- §4 Data rules, new bullet **"One curve for both modes"**: dates and wavelengths both render through
  `render.to_uint8_asinh`. Before, §4 required only a *global* stretch, which both modes satisfied
  with different curves.
- `Docs/phase-7-corrections.md` §1.1 said to put `RENDER_VERSION` in `sequence_key` and `cube_key`.
  It is in `frame_key` too, because `/preview` serves bytes cached under that key and they never
  expire: bumping two of three keys would leave already-seen frames rendering with the old curve.

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
