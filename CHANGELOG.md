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
