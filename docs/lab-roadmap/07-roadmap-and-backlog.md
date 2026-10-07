# Part 7: Development Roadmap, Prioritised Backlog, First Implementation Tasks

> Report sections covered: **25** Development roadmap · **26** Prioritised backlog · **27** First 10–20 implementation tasks.
>
> Effort assumes **one developer, ~10–15 h/week**, with Claude Code as a pair programmer. "Weeks" are
> calendar weeks at that pace. Estimates have roughly ±50% uncertainty. The sequence matters more than the dates.

---

## 25. Development roadmap

### How this differs from the sequence in the brief, and why

1. **A correctness phase comes first** (Phases 0–2). The audit shows the current measurements are
   invalid. Archives, AI and hardware all multiply whatever the core produces, so the core must be right first.
2. **The "What am I looking at?" evidence engine is built deterministically before any LLM**
   (Phase 3 before Phase 4). The LLM then renders verified statements instead of improvising.
3. **The own-telescope *data* pipeline comes before own-telescope *control*** (Phase 5 before 7–8).
   Capture with existing software on day one; ingest and analyse with the platform.
4. **Hardware control is developed against simulators in parallel**, and is gated by a safety kernel.
   Autonomy comes last and is optional.
5. **Wavelength expansion** (X-ray, radio) comes after the optical/IR engine is trustworthy, because
   each needs its own domain tooling.

```
Phase:  0   1   2   3   4   5   6   7   8   9   10  11
        │Honest baseline
            │JWST/HST product core
                │Measurement engine
                    │Discovery + cross-mission + evidence engine v1
                        │Knowledge/RAG + assistant (MCP)
                     ▲  telescope purchase decision point (after Phase 3; informed by §22)
                            │Own-data pipeline (ingest-only)
                                │Observation planning
                            │──────HAL + safety kernel on simulators (parallel track)
                                        │Assisted control on real hardware
                                            │Science workflows + submissions
                                                │Spectroscopy (when hardware exists)
                                                    │Trusted automation → autonomy
```

### Phase 0: Honest baseline (≈ 1–2 weeks)
- **Objective:** Make the repository truthful, installable and testable.
- **Features:**
  - legacy freeze;
  - README corrections;
  - removal of the fabricated filenames;
  - package skeleton (`pyproject`, `src/astroledger`, uv lock, ruff, pytest, CI);
  - `CLAUDE.md` + SessionStart hook *(done)*;
  - audit checks become tests.
- **Architecture:** `core`, `provenance` (v0 sidecars).
- **Dependencies:** none.
- **Scientific requirements:** none new; remove false claims.
- **Deliverables:** tagged release `v0.1.0`; green CI; corrected README.
- **Difficulty:** 1. **Risk:** low.
- **Do NOT build yet:** any new feature.

### Phase 1: JWST/HST product core (≈ 4–6 weeks)
- **Objective:** Correctly find, fetch, open and describe JWST and HST imaging products.
- **Features:**
  - `archives/mast` adapter (astroquery `Observations` + `MastMissions`), product-level aware, with checksums and cache;
  - MEF reader → `ImageProduct` (SCI/ERR/DQ, units, WCS/GWCS);
  - `Bandpass` resolver (NIRISS PUPIL, NIRCam pupil-wheel pairs, HST filters);
  - mode router (refuse unsupported `EXP_TYPE`);
  - display layer (stretches, Lupton RGB, WCSAxes);
  - provenance v1 (SQLite);
  - CLI `fetch`/`inspect`.
- **Dependencies:** Phase 0.
- **Scientific requirements:**
  - B1 photometry agrees with pipeline catalogues within errors;
  - bandpass resolver passes header test fixtures;
  - units preserved end-to-end.
- **Deliverables:** `astroledger inspect file.fits` prints the L1 fact sheet (§14.2); notebook B1; science tests.
- **Difficulty:** 3. **Risks:** heavy dependencies (jwst/CRDS); mitigate with optional extras and Stage-3 products first.
- **Do NOT build yet:** running the JWST pipeline locally, spectroscopy, other archives, AI.

### Phase 2: Measurement engine (≈ 6–8 weeks)
- **Objective:** Statistically valid detection, photometry and astrometry with uncertainties.
- **Features:**
  - background models;
  - matched-filter detection + deblending;
  - false-positive and completeness tooling (B5);
  - aperture photometry with ERR and correlated-noise correction;
  - Gaia cross-match with epoch propagation;
  - astrometric QA (I1);
  - reprojection and PSF matching.
- **Dependencies:** Phase 1.
- **Scientific requirements:**
  - negative-image false-positive rate reported;
  - injection–recovery completeness curves;
  - astrometric residuals vs Gaia reported per image.
- **Deliverables:** `astroledger measure`; validation report notebook; science test suite.
- **Difficulty:** 3–4. **Risks:** correlated noise and crowded fields; scope to isolated sources first.
- **Do NOT build yet:** PSF photometry for crowded fields (that is A1), ML.

### Phase 3: Discovery, cross-mission, evidence engine v1 (≈ 6–8 weeks)
- **Objective:** Answer "What am I looking at?" and "What observations exist?" deterministically.
- **Features:**
  - VO layer (pyvo TAP/ObsCore/SIA, MOCServer, hips2fits);
  - CDS adapters (Sesame, SIMBAD, VizieR, XMatch);
  - Gaia, IRSA, PS1, Legacy Surveys adapters;
  - SkyBoT;
  - cross-match with P_chance and conflicts;
  - `interpret` evidence engine with L1/L2/L3 rules;
  - comparison engine (§14.5) for imaging.
- **Dependencies:** Phase 2.
- **Scientific requirements:**
  - zero fabricated identities on the evaluation images;
  - every L2 statement has evidence refs;
  - conflicts surfaced.
- **Deliverables:** `astroledger explain file.fits` → structured evidence report (JSON + Markdown); I2 notebook.
- **Difficulty:** 4. **Risks:** rule coverage; start with stars, galaxies, nebulae and artefacts.
- **Do NOT build yet:** an LLM narrative layer, X-ray/radio analysis, web UI.
- **Decision point:** telescope purchase (use §22, measure your site's seeing and sky brightness first).

### Phase 4: Knowledge layer + assistant (≈ 6–8 weeks)
- **Objective:** A literature-grounded assistant operating the platform through tools.
- **Features:**
  - ADS/SciX + arXiv clients;
  - hybrid RAG index with passages;
  - object ↔ paper ↔ dataset links;
  - MCP server exposing Phase 1–3 tools;
  - orchestrator prompt + claim verifier;
  - tutor mode;
  - evaluation suite (§15.5) in CI.
- **Dependencies:** Phase 3. API keys (ADS token, LLM).
- **Scientific requirements:**
  - fabrication-trap pass rate 100%;
  - every literature claim carries bibcode + passage;
  - level-promotion errors = 0 on the evaluation set.
- **Deliverables:** use from the Claude app (desktop and iPad via remote MCP over a VPN); workflows 1 and 6 runnable.
- **Difficulty:** 4. **Risks:** retrieval quality; rate limits; cost. Mitigate with caching and evaluations.
- **Do NOT build yet:** fine-tuning, multi-agent frameworks, custom chat UI.

### Phase 5: Own-telescope data pipeline, ingest-only (≈ 4–6 weeks; starts when hardware arrives)
- **Objective:** Science from your telescope using existing capture software.
- **Features:**
  - FITS ingest from N.I.N.A./Ekos/vendor software (header normalisation, equipment profiles);
  - photon-transfer curve (gain and read noise);
  - master calibration frames (ccdproc);
  - plate solving;
  - differential photometry with Gaia-XP-calibrated comparison stars;
  - personal observation database (§11.3).
- **Scientific requirements:**
  - measured gain/read noise;
  - photometric precision vs CCD-equation prediction reported;
  - every result traceable to raw frames.
- **Deliverables:** first variable-star or transit light curve with full provenance.
- **Difficulty:** 3. **Risks:** header inconsistencies across capture software; flats quality.
- **Do NOT build yet:** device control.

### Phase 6: Observation planning (≈ 3–4 weeks)
- **Features:**
  - site and equipment profiles;
  - astroplan constraints;
  - ETC (§13.4) calibrated with Phase 5 measurements;
  - weather forecast adapter;
  - target feeds (AAVSO, ExoClock/transit predictions, MPC/NEOCP, TNS bright);
  - scoring + scheduler;
  - draft plans.
- **Scientific requirements:** ETC predictions within ~30% of achieved S/N.
- **Deliverables:** "What can I observe tonight?" (workflow 2).
- **Do NOT build yet:** automatic execution.

### Phase 7: HAL + safety kernel on simulators (parallel track, ≈ 6–8 weeks)
- **Features:**
  - HAL interfaces;
  - Alpaca backend (OmniSim) and INDI backend (INDI simulators);
  - safety kernel (limits, horizon, Sun avoidance, tokens, tiers);
  - sequencer state machine;
  - plan DSL + validator;
  - audit log;
  - fault-injection tests.
- **Scientific / safety requirements:** 100% of invalid plans rejected in tests; watchdog tested.
- **Deliverables:** simulated observing night end-to-end.
- **Do NOT build yet:** NL control of real hardware, autonomy.

### Phase 8: Assisted control on real hardware (≈ 4–6 weeks)
- **Features:**
  - Tier 0/1 control of the real mount, camera, wheel and focuser;
  - PHD2 integration;
  - plate-solve centring;
  - calibration-frame sequences;
  - NL → DSL proposals via the assistant with confirmation.
- **Requirements:** supervised operation only; hardware interlocks installed if there is a roof.
- **Deliverables:** workflow 3 ("Observe M51") under confirmation.
- **Do NOT build yet:** unattended operation.

### Phase 9: Science workflows + community submissions (ongoing)
- AAVSO extended format export; ADES export for the MPC; ExoClock/ETD submission formats.
- Projects R1, R6, R7.
- **Deliverables:** first accepted external submissions.

### Phase 10: Spectroscopy (when a spectrograph exists, ≈ 6–8 weeks)
- specreduce extraction, arc-lamp wavelength calibration, flux calibration with standard stars, telluric handling, line fitting, reference-spectrum comparison.
- **Do NOT build before** the hardware exists. Archive spectra (SDSS, JWST x1d) can be supported read-only earlier.

### Phase 11: Trusted automation → autonomy (≈ 8+ weeks; optional)
- **Features:**
  - signed plans (Tier 2);
  - unattended monitoring;
  - recovery policies;
  - roof/dome control with hardware interlocks;
  - alerting.
- **Entry criteria:** ≥ 20–30 supervised nights logged; all fault-injection tests pass; independent rain interlock installed and tested.
- **Do NOT do:** enable autonomy on a portable setup, or without hardware interlocks.

Later and continuous: X-ray/radio analysis (CIAO/SAS/CASA), simulation projects, ML models, web UI, Postgres migration, DaCHS publishing.

---

## 26. Prioritised backlog

Scores 1–5. Priority: P0 (now) → P3 (later). Dependency impact = how much later work it unblocks.

| # | Task | Sci. value | Tech. value | Difficulty | Dependencies | Priority |
|--:|------|:--:|:--:|:--:|------|:--:|
| 1 | Remove fabricated filenames; correct README claims and synthetic-image label | 5 | 2 | 1 | — | **P0** |
| 2 | Freeze legacy scripts in `legacy/` with a README linking to the audit | 2 | 3 | 1 | — | **P0** |
| 3 | Package skeleton (`pyproject`, `src/astroledger`, uv lock, ruff, pytest, CI) | 2 | 5 | 2 | — | **P0** |
| 4 | Convert `audit_checks.py` into science-invariant regression tests | 4 | 4 | 1 | 3 | **P0** |
| 5 | MEF reader → `ImageProduct` with SCI/ERR/DQ mask, unit, WCS | 5 | 5 | 2 | 3 | **P0** |
| 6 | `Bandpass` resolver (FILTER+PUPIL; NIRISS, NIRCam pairs; HST) with header fixtures | 5 | 4 | 2 | 3 | **P0** |
| 7 | Display layer separated from data (stretches, Lupton RGB with chromatic ordering, WCSAxes) | 3 | 4 | 2 | 5 | **P0** |
| 8 | MAST adapter: target search → observation table → product levels → checksummed fetch | 4 | 5 | 3 | 3 | **P0** |
| 9 | Provenance v1 (`@step`, SQLite, sidecars, file hashes, CAL_VER/CRDS_CTX) | 5 | 5 | 3 | 3 | **P0** |
| 10 | `astroledger inspect`: L1 fact sheet for any FITS | 4 | 4 | 2 | 5, 6 | **P1** |
| 11 | Aperture photometry with errors; JWST unit conversion + aperture corrections; validate vs `_cat.ecsv` | 5 | 4 | 3 | 5, 6 | **P1** |
| 12 | Background2D + matched-filter detection + deblending; negative-image test | 5 | 4 | 3 | 5 | **P1** |
| 13 | Injection–recovery completeness tooling (STPSF) | 5 | 3 | 3 | 12 | **P1** |
| 14 | Gaia cross-match with epoch propagation; astrometric QA | 5 | 4 | 3 | 5 | **P1** |
| 15 | Mode router (`EXP_TYPE`) with explicit refusals | 3 | 3 | 1 | 5 | **P1** |
| 16 | HST reader (PHOTFLAM/PHOTFNU, multi-chip, drc/flc) + HSC validation | 4 | 4 | 3 | 5, 11 | **P1** |
| 17 | Reprojection + PSF matching utilities | 4 | 4 | 3 | 5 | **P1** |
| 18 | VO layer (pyvo TAP/ObsCore, MOCServer, hips2fits) | 4 | 5 | 3 | 8 | **P1** |
| 19 | CDS adapters (Sesame, SIMBAD TAP incl. bibliography, VizieR, XMatch) | 5 | 4 | 2 | 18 | **P1** |
| 20 | Cross-match engine (error-based radius, P_chance, conflicts) | 5 | 4 | 3 | 14, 19 | **P1** |
| 21 | Evidence engine (`Statement`, rules for star/galaxy/nebula/artefact; downgrade-only) | 5 | 5 | 4 | 10, 20 | **P1** |
| 22 | `astroledger explain` report (JSON + Markdown) | 4 | 4 | 2 | 21 | **P1** |
| 23 | Comparison engine (resolution, depth, bandpass table; convolved views) | 4 | 3 | 3 | 17, 18 | **P2** |
| 24 | ADS/SciX + arXiv clients; RAG index with passages | 4 | 4 | 3 | 9 | **P2** |
| 25 | MCP server exposing tools (Tier 0) | 3 | 5 | 2 | 10, 22 | **P2** |
| 26 | Claim verifier + evaluation suite in CI | 5 | 4 | 3 | 24, 25 | **P2** |
| 27 | Own-data ingest + photon-transfer curve + ccdproc masters | 5 | 4 | 3 | 5, 9 | **P2** (P0 once hardware arrives) |
| 28 | Differential photometry with Gaia-XP-calibrated comparisons | 5 | 3 | 3 | 27, 14 | **P2** |
| 29 | Planner (astroplan + ETC + weather + target feeds) | 4 | 4 | 3 | 27 | **P2** |
| 30 | HAL interfaces + Alpaca backend on OmniSim | 2 | 4 | 3 | 3 | **P2** |
| 31 | Safety kernel + sequencer + plan DSL + audit log + fault injection | 3 | 5 | 4 | 30 | **P2** |
| 32 | INDI backend | 2 | 4 | 3 | 30 | **P3** |
| 33 | PHD2 + plate-solver clients; centring routine | 3 | 4 | 3 | 30 | **P3** |
| 34 | Submission exporters (AAVSO, ADES/MPC, ExoClock) | 4 | 3 | 2 | 28 | **P3** |
| 35 | Spectroscopy module (archive read-only first) | 3 | 3 | 3 | 5 | **P3** |
| 36 | Trusted automation / autonomy | 3 | 4 | 5 | 31–33 + nights logged | **P3** |
| 37 | X-ray/radio adapters with domain tooling | 3 | 3 | 4 | 18 | **P3** |

---

## 27. First 10–20 implementation tasks (do these, in this order)

Each task is sized for one or two sessions with Claude Code, and has a concrete "done when".

**Progress:**
- Tasks 1–2 done: README corrected, fabricated filenames removed, legacy frozen in `legacy/` with a checksum test.
- Tasks 3–4 done: `pyproject.toml` + `uv.lock` + `src/astroledger/`, ruff, CI on Python 3.11/3.13; `tests/science/test_legacy_defects.py` documents 7 legacy defects as strict expected failures.
- **Phase 0 complete.**
- Task 5 done: `astroledger.io.open_image` / `open_images` → `ImageProduct` (SCI/ERR/DQ by EXTNAME, unchanged pixels, NaN + mission-aware DQ mask, raw DQ kept, BUNIT incl. HST/camera forms, celestial WCS or None, both headers, file SHA-256, reader notes); tested on JWST cal/i2d/rate/uncal, HST two-chip flt and drz, and plain camera frames.
- Task 6 done: `Bandpass.from_header` (NIRCam pupil-wheel filters, NIRISS CLEAR/PUPIL, HST ACS wheels); nominal wavelength from the filter-naming convention, pivot only from `PHOTPLAM`; tested on authentic NGC 3132 headers.
- Task 7 done: `astroledger.viz` (`show`, `make_rgb` with reprojection and chromatic ordering, `show_rgb`); data proven unchanged. Composites use independent per-channel asinh scaling (representative colour), not a Lupton stretch.
- Task 8 done: `astroledger.provenance` (`@step`, SQLite `ProvenanceStore`, JSON sidecars, git/package versions).
- Task 9 done: `astroledger.archives.mast` (astroquery search with bandpass resolution) and `archives.cloud` (MAST's public AWS copy: listing, ETag-verified fetch, range-request cutouts with budget ledger). Live MAST API search is untested here because the environment blocks `mast.stsci.edu`; S3 access is live-tested.
- Task 10 done: `astroledger inspect FILE [--json]`.
- Task 11 done: `astroledger.photometry.aperture_photometry_table`; on authentic NGC 3132 F405N data it reproduces the JWST pipeline catalogue (jwst 2.0.1) to <1e-6 in flux and identically in error; authentic stamps in `tests/data/real` keep this in CI.
- Task 12 done: `astroledger.imaging.detect` (two-pass background, matched filter, threshold from unconvolved RMS, optional deblending (off by default, as in the JWST pipeline, because it shreds bright stars' wings), `near_bright_source` heuristic flag for PSF wings/spike fragments, negative-image false-positive estimate with locations). On real data: 34/34 pipeline sources on clean sky recovered, 4 negative-image detections there; inside the nebula, false positives concentrate where the background model cannot follow structured emission.
- Task 13 done: `astroledger.imaging.injection_recovery` + `empirical_psf` + `plot_completeness`. Point sources are injected into a copy of the image (never the original), detected with the science settings and matched within 1.5 px. The result gives completeness per level with 68% Wilson intervals, 50%/90% limits with 68% ranges, a per-source table for diagnosing losses, and a provenance record. STPSF was not used: its data files are on a host this environment blocks. The empirical PSF is built from the image itself, with each star's local background subtracted; without that step the PSF carried a nebular pedestal and injected sources were too extended (found on real data and fixed, with a regression test). On NGC 3132 F405N (40 sources per level, AB 18–27): clean sky 50% at AB 24.76 [24.72, 24.80] and 90% at 24.33; inside the nebula 90% only at AB 21.1 and 50% at 23.4 [23.3, 24.6]. There, small-scale Brackett-α structure raises the background RMS, and with it the detection threshold, to 1–3.5 MJy/sr. Figure, tables and provenance: [`docs/results/ngc3132_f405n_completeness/`](../results/ngc3132_f405n_completeness/); rerun with `examples/ngc3132_completeness.py`.
- Task 14 done: `astroledger.archives.gaia.gaia_cone` reads Gaia DR3 selectively from MAST's HATS Parquet copy on AWS (partition index, footer, then only the row groups whose `source_id` range covers the cone; every byte goes through the download ledger). `astroledger.astrometry` adds `observation_epoch` (MJD-AVG/EXPMID, HST EXPSTART/EXPEND, DATE-OBS fallback), `propagate` (great-circle proper-motion propagation with error growth; two-parameter solutions flagged), `astrometric_qa` and `plot_astrometric_qa`. `astrometric_qa` does one-to-one matching via `crossmatch.match_nearest`, excludes stars without proper motion and near the mask, applies robust 2-D clipping, and reports the median offset with its error, RMS, robust scatter and a shift/rotation/scale fit. On four authentic NGC 3132 products, NIRCam Stage-3 mosaics agree with Gaia DR3 to 10–30 mas but differ from one another by up to about 20 mas; the JWST pipeline's own catalogues confirm the offsets are in the WCS. The MIRI Stage-2 exposure is offset by about 50 mas and rotated by about 75″. Results: [`docs/results/ngc3132_astrometry/`](../results/ngc3132_astrometry/).
- **Next: task 13** (injection–recovery completeness).

| # | Task | Done when |
|--:|------|-----------|
| 1 | Delete the renaming in `jwst_real_data_demo.py`, label the README hero image as synthetic, and remove unsupported claims | README states actual capabilities; no file is renamed from archive names |
| 2 | Move the nine scripts to `legacy/` unchanged + `legacy/README.md` | `python legacy/jwst_demo.py` still runs; README links to the audit |
| 3 | Create `pyproject.toml` (`astroledger`, Python ≥ 3.11, extras `[jwst]`, `[dev]`), `src/astroledger/__init__.py`, `uv.lock`, ruff config, GitHub Actions running `pytest -m "not remote"` | CI green on an empty test suite |
| 4 | Port `docs/lab-roadmap/audit_checks.py` into `tests/science/test_legacy_defects.py` as **xfail-documented** checks | Tests document the defects; they are referenced by the new implementations |
| 5 | Implement `astroledger.io.open_image(path) -> ImageProduct` (SCI/ERR/DQ by EXTNAME, NaN+DQ → mask, unit from BUNIT, WCS from SCI header, full header kept) | Tests on generated JWST-like and HST-like fixtures (including 2-chip HST) |
| 6 | Implement `astroledger.core.Bandpass.from_header()` with a table of NIRCam/NIRISS/MIRI/HST elements and pivot wavelengths from synphot/SVO | Fixtures: NIRISS `CLEAR`+`F150W` → F150W; NIRCam `F444W`+`F405N` → F405N; three NIRISS bands → three keys |
| 7 | `astroledger.viz`: `show(image)` with WCSAxes + `PercentileInterval`/`AsinhStretch`; `rgb(images)` with reprojection, chromatic ordering and `make_lupton_rgb` | Data arrays provably unchanged (hash before and after display) |
| 8 | `astroledger.provenance.step` decorator + SQLite store + JSON sidecars | Every output has a sidecar with inputs' SHA-256, params, versions, git commit |
| 9 | `astroledger.archives.mast`: `search(target, instrument=…, level=3)` → table with program, PI, instrument, mode, resolved bandpass, exposure, calib level, rights; `fetch(product)` with checksum | Network-marked integration test reproduces a MAST Portal query |
| 10 | CLI `astroledger inspect <file>` → L1 fact sheet (§14.2) | Correct on real NIRCam, NIRISS, MIRI, WFC3 and ACS files |
| 11 | `astroledger.photometry.aperture()` with errors and JWST MJy/sr → AB conversion (PIXAR_SR + APCORR) | Agrees with a pipeline `_cat.ecsv` within errors on a validation image (notebook B1) |
| 12 | `astroledger.imaging.detect()` (Background2D, matched filter, threshold from unconvolved RMS, deblend) + negative-image FP estimate | On pure noise, detections ≤ expected FP count; the legacy test flips from failing to passing |
| 13 | Injection–recovery utility | Completeness curve plotted and stored with provenance |
| 14 | Gaia DR3 cross-match with epoch propagation + astrometric QA report | Residual statistics reported per image (I1) |
| 15 | Mode router (`EXP_TYPE`) with explicit refusals | Spectroscopic, coronagraphic and TSO files refused with a clear message |
| 16 | CDS adapters: Sesame resolve, SIMBAD TAP (otype, ids, bibliography), VizieR query | Cached, provenance-recorded; no identity field generated outside a retrieved record |
| 17 | Cross-match engine with error-based radius, P_chance, conflict reporting | Unit tests with synthetic catalogues of known density |
| 18 | `interpret` evidence engine v1 (star/galaxy/nebula/artefact rules) + `astroledger explain` | Evaluation images: zero fabricated identities; every L2 has evidence |
| 19 | Minimal MCP server exposing `inspect`, `search`, `explain` (read-only) | Usable from Claude Code; then from the Claude app via a remote connector |
| 20 | Notebook I2 (NGC 3132 narrow bands, program 2733), the first public "reproduced analysis" | Notebook regenerated from provenance by `astroledger reproduce` |

To start: open a Claude Code session on this repository (from the iPad app or anywhere) and say
*"Do task 1 from docs/lab-roadmap/07-roadmap-and-backlog.md §27"*. `CLAUDE.md` provides the rules each session needs.
