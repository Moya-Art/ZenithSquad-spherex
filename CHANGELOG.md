# Changelog

Notable changes to this project, recorded one entry per build phase. Newest phase first.
Each entry names the pull request and commit that landed it.

Entry format:

```markdown
## Phase N — <name> — YYYY-MM-DD
Merged in [#N](pull-request-url). Commit `<sha>`.

### Added / Changed / Fixed / Removed
- what changed, and why it matters
```

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
