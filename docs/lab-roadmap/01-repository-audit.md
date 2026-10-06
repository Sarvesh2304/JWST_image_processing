# Part 1: Repository Audit (Code Review and Scientific Review)

> Report sections covered: **1** Executive assessment · **2** Current repository capabilities ·
> **3** Code review · **4** Scientific review · **5** Critical problems · **6** Immediate improvements
>
> Audit date: 2026-10-06. Commit audited: `cccbb2c` (the only commit). Every claim below marked
> **[verified]** was reproduced by running the code (see [`audit_checks.py`](audit_checks.py), which reproduced
> 8 of 8 defects on commit `cccbb2c` with astropy 8.0.1, photutils 3.0.0, matplotlib 3.11.2, numpy 2.5.3;
> check 6 now passes because this commit adds `astroquery` to `requirements.txt`).
> Claims marked **[static]** come from reading the source. **[external]** claims were checked against
> official or published sources.

---

## 1. Executive assessment

**What the repository is:** about 2,900 lines in nine flat Python scripts. Together they download
FITS files, apply cosmetic image operations, and produce matplotlib figures. It is an
**image-display prototype**, not a scientific pipeline. It uses the right libraries (Astropy,
photutils, astroquery, scikit-image) and is a reasonable seed, but in its current form it
**cannot produce a trustworthy scientific measurement**, and parts of it do not run against real JWST data.

**Key findings:**

| # | Finding | Evidence |
|---|---------|----------|
| 1 | The main pipeline (`jwst_main.py` → `JWSTImageProcessor`) **cannot load any JWST science file**. It reads HDU 0, but JWST stores pixels in the `SCI` extension. | [verified] check 1. An end-to-end run of `jwst_main.py --process-only` on a JWST-structured file ends with "No files processed successfully". |
| 2 | Target-based search (`--target`) **cannot work**. The legacy downloader posts JSON to a non-existent endpoint path, with `ra=0, dec=0` and parameters the service does not accept. | [static] check 7 |
| 3 | The only real-data path (`find_jwst_data.py`) downloads **the first row of an unfiltered query over the whole JWST collection**. It has nothing to do with any requested target, and it prefers Stage-1/2 `RATE` files (DN/s, no flux calibration, no WCS). | [static] |
| 4 | "Calibration" is a global median subtraction followed by **clipping negatives to zero**. On pure Gaussian noise this clips 50% of pixels, and the "3σ" detector then finds **600 spurious sources** in a 1024² image that contains none. | [verified] check 2 |
| 5 | Filter identity is read from `FILTER` alone. For NIRISS (`FILTER=CLEAR`, bandpass in `PUPIL`) and for NIRCam pupil-wheel filters (for example F405N is recorded as `FILTER=F444W, PUPIL=F405N`), the bandpass is **mislabelled**. Results are keyed by that label, so **images overwrite each other**. | [verified] check 5: three NIRISS bands collapse to one key. [external] NIRCam filter and pupil pairing. |
| 6 | `jwst_real_data_demo.py` saves archive files under **fabricated names**: `jw02756…_nrca1_rate.fits` becomes `NGC_3132_F444W.fits`. Program 2756 is a DDT supernova follow-up in Abell 2744, not NGC 3132 (NGC 3132 was ERO program 2733, which did not use F444W). Also, NRCA1 is a short-wavelength detector, so it physically cannot record F444W or F277W. | [external] |
| 7 | 4 of the 6 plotting functions crash under current matplotlib (`ZScaleInterval` passed as a `norm`), and a 5th crashes for linear stretch. `plot_source_catalog` also uses an undefined name `u` and a removed photutils attribute. | [verified] checks 3–4 and pyflakes |
| 8 | `astroquery`, the dependency of the only working download path, is **missing from `requirements.txt`**. | [verified] check 6 (*fixed in this commit*) |
| 9 | The README overclaims ("publication-quality", "supports NIRSpec/MIRI", "complete pipeline"). Its hero image is **synthetic**, and its "RGB composite" is the same image shifted by 10 and 20 pixels. | [static] `create_sample_visualization.py` lines 63–65 |
| 10 | There are no tests, no packaging, no persistence (nothing is ever written to `processed/`), no logging, and warnings are suppressed globally. | [static] |

**Bottom line:**
- **Keep** the repository, its name and history, and the instinct to build on Astropy and astroquery.
- **Do not** refactor the scripts in place. Freeze them under `legacy/`.
- **Build** a small, tested, installable package beside them. Its core idea is that every pixel
  array carries its units, uncertainty, mask, WCS, bandpass and provenance.

Everything in the larger vision (archives, the AI assistant, the observatory) depends on this core
being correct. That is why Phase 0–2 of the roadmap ([07](07-roadmap-and-backlog.md)) is about
correctness rather than features.

---

## 2. Current repository capabilities

### 2.1 Inventory

| File | Lines | Role | State |
|------|------:|------|-------|
| `jwst_main.py` | 264 | CLI: download → process → visualise | Download path broken (finding 2). Process path broken (finding 1). `--visualize-only` always exits, because nothing is persisted. |
| `jwst_data_downloader.py` | 199 | Raw-HTTP MAST client | Non-functional (finding 2). |
| `find_jwst_data.py` | 306 | astroquery download + its own processing + plots | **The only real-data path.** Untargeted (finding 3). Picks the "largest HDU" heuristically. |
| `jwst_image_processor.py` | 362 | Calibration, denoise, enhance, detection, RGB | Statistically invalid (findings 4–5). Cannot load JWST files (finding 1). |
| `jwst_visualizer.py` | 455 | Plot functions | Mostly crashes (finding 7). |
| `jwst_real_data_demo.py` | 354 | Hard-coded downloads + plots | Fabricated metadata in filenames (finding 6). |
| `jwst_demo.py` | 229 | Synthetic "galaxy" demo | **Runs** [verified]. Purely synthetic. |
| `create_sample_visualization.py` | 96 | Makes the README image | Synthetic; fake RGB. |
| `project_summary.py` | 137 | Prints a success banner | No functional content. |
| `setup_github.sh` | 45 | `git init` + commit | Obsolete now that the repository exists. |
| `jwst_data/visualizations/sample_jwst_processing.png` | 9.4 MB | README image | 3465×2955 px at 300 dpi. Synthetic. |

### 2.2 Capability matrix: what it can and cannot do

Legend: ✅ works · ⚠️ works with major caveats · ❌ broken · 🚫 claimed but absent

| Capability | Status | Detail |
|------------|:------:|--------|
| Search MAST by target / instrument | ❌ | Legacy downloader: wrong endpoint and parameters, searches at (0, 0). |
| Download real JWST files | ⚠️ | `find_jwst_data.py` only, and it downloads an arbitrary first observation. |
| Choose product level (uncal / rate / cal / i2d) | ⚠️ | Hard-coded preference `RATE > CAL > UNCAL > I2D`. This is the opposite of what an imaging user normally wants. |
| Read JWST multi-extension FITS | ❌ / ⚠️ | Main pipeline reads HDU 0 (empty). `find_jwst_data.py` takes the largest HDU. For `uncal` that is the 4-D ramp cube. For mosaics with more than 32 inputs the `CON` context cube outgrows `SCI` and would be picked instead. |
| Use ERR / DQ / variance arrays | 🚫 | Ignored everywhere. |
| Units (`BUNIT`, `PIXAR_SR`, `PHOTFLAM`) | 🚫 | Never read. Colourbars say "Flux" on normalised, log-stretched data. |
| WCS / sky coordinates | ❌ | WCS is built from the primary header (no celestial WCS there) and never used. All plots are in pixels. `rate` files have no WCS at all. |
| Calibration | 🚫 | Only global background subtraction (see §4). |
| Source detection | ⚠️ | Runs, but the false-positive rate is uncontrolled (600 false sources in pure noise). |
| Photometry | 🚫 | `SourceCatalog` fluxes are computed without errors, in arbitrary units, and never output. |
| Astrometry / cross-matching | 🚫 | Absent. |
| Multi-filter / RGB | ⚠️ | Same-shape arrays only. No reprojection. Channel order is arbitrary. Same-filter images overwrite each other. |
| NIRSpec / MIRI spectroscopy, IFU, WFSS, TSO | 🚫 | Claimed in the README. Spectral data would be processed as an image. |
| HST or any other mission | 🚫 | — |
| Persistence of results | 🚫 | `processed/` is created but never written. |
| Tests / CI / packaging / docs build | 🚫 | — |
| Synthetic demonstrations | ✅ | Run, but are not JWST data and are not labelled as such in the README image. |

---

## 3. Code review (engineering)

### 3.1 Architecture

- **Four divergent copies of "the pipeline".** `JWSTImageProcessor`, `find_jwst_data.process_jwst_pipeline`,
  `jwst_real_data_demo.process_jwst_data` and `jwst_demo.process_image` each implement their own
  background, smoothing and stretch, with different constants:
  - background: median, 5th percentile, or 10th percentile;
  - smoothing: σ = 1.0 or 1.2;
  - stretch: `log1p(x·1000)`, `x·50` or `x·100`.

  The same file gives different "results" depending on which script runs it. **Fix:** one
  implementation, behind one API, covered by tests.
- **No package.** These are flat scripts with module-level side effects:
  - constructors create directories;
  - `plt.style.use('dark_background')` changes global state;
  - `warnings.filterwarnings('ignore')` runs at import time.
- **Disconnected stages.** astroquery writes to `jwst_data/raw/mastDownload/JWST/<obs_id>/…`, but
  `jwst_main.py` only scans `jwst_data/raw/*.fits`. The only working downloader and the processor
  therefore never meet.
- **Dead control flow.** `jwst_main.py` checks `'processed_filters' not in locals()` and then always
  returns. There is no load path.

### 3.2 Error handling and observability

- Broad `except Exception: print(...); return None` everywhere. Failures look like empty results.
  For example, a malformed MAST request prints "No observations found", which is wrong
  information rather than an error.
- `print` instead of `logging`. No run log, so no record of what happened.
- **Global warning suppression is a scientific hazard.** Astropy emits `FITSFixedWarning`,
  unit-parsing warnings and WCS warnings exactly when metadata is suspicious, and the code silences all of them.

### 3.3 Correctness defects (non-scientific)

| Location | Defect | Evidence |
|----------|--------|----------|
| `jwst_visualizer.py` (4 functions) | `norm=ZScaleInterval()` raises `TypeError` in matplotlib ≥ 3.x | [verified] |
| `jwst_visualizer.py:265` | `u` undefined (`astropy.units` not imported) | [verified] pyflakes |
| `jwst_visualizer.py:264` | `semimajor_axis_sigma` no longer exists in photutils (now `semimajor_sigma`) | [verified] |
| `jwst_visualizer.py:311–317` | `n_filters == 1` → `axes=[axes]` then `.flatten()` on a list → `AttributeError` | [static] |
| `jwst_image_processor.py:300` | Parameter `filters` shadows the imported `skimage.filters` | [verified] pyflakes |
| `jwst_image_processor.py:118` | Division by zero for a constant image (`max == min`) | [static] |
| `jwst_real_data_demo.py:273` | Writes `response.content` to disk without validating that it is FITS | [static] |
| all | 18 unused imports; f-strings without placeholders | [verified] pyflakes |

### 3.4 Dependencies and reproducibility

- `requirements.txt`:
  - is unpinned (`>=` only), with no lockfile and no Python version;
  - **omits `astroquery`** (*added in this commit*);
  - lists unused packages (`ccdproc`, `astropy-healpix`, `astropy-sphinx-theme`, `ipywidgets`, `pillow`).
- Results depend on the current working directory (relative paths are hard-coded), on random
  seeds (the synthetic demos are unseeded), and on whatever MAST returns first that day.
- MAST reprocesses data as the JWST pipeline and reference files evolve. The latest `jwst` package
  is **3.0.0 (July 2026, CRDS context 1581)** [external]. A file downloaded today can differ from
  one downloaded last year, and nothing records `CAL_VER` or `CRDS_CTX`.

### 3.5 Performance

- Every file keeps four full-resolution `float64` copies (original, calibrated, denoised,
  enhanced) plus figures. A 10k × 10k Stage-3 mosaic would need about 3.2 GB for the arrays alone.
- `ndimage.median_filter` and `denoise_tv_chambolle` on full mosaics are slow, and they are
  scientifically unnecessary (see §4).
- Every figure is saved at 300 dpi and 12–20 inches wide, which is why the PNG in Git is 9.4 MB.

### 3.6 Maintainability and extensibility

There are no seams to extend. Adding HST, MIRI imaging or a personal telescope would mean another
copy of the pipeline. The roadmap replaces this with three extension points:
- **mission adapters** (search, products, reader);
- **product types** (image, spectrum, cube, time series, catalogue);
- **processing steps** (pure functions that record provenance).

---

## 4. Scientific review

Each issue uses the requested five-part structure:
- **(a)** what the code does;
- **(b)** why it is insufficient;
- **(c)** what should replace it;
- **(d)** why it matters scientifically;
- **(e)** difficulty.

Classification: **[E]** existing capability, **[I]** improvement, **[N]** new capability, **[R]** research-grade.

### S1. Product level is ignored (rate vs cal vs i2d vs uncal) [I]
- **(a)** `find_jwst_data.py` prefers `RATE`, then `CAL`, `UNCAL`, `I2D`. It treats whichever it gets as "the image".
- **(b)** `rate` is the Stage-1 output: a slope image in **DN/s**, with no flat field, no photometric calibration and **no WCS** (WCS is assigned in Stage 2). `uncal` is a 4-D ramp cube. Only `cal` (Stage 2, per exposure, MJy/sr, distortion-corrected GWCS) and `i2d` (Stage 3, resampled and combined) are science-ready imaging products.
- **(c)** Product-level-aware retrieval:
  - default to Stage-3 `i2d` plus the pipeline source catalogue for exploration;
  - use Stage-2 `cal` when per-exposure measurement or custom Stage-3 processing is needed;
  - use `uncal` only to rerun the official pipeline locally.
- **(d)** The repository's "real JWST data success" was obtained on uncalibrated count rates. No physical quantity can be read from them.
- **(e)** Low.

### S2. FITS extension model [I]
- **(a)** Reads HDU 0 (`jwst_image_processor`), or the largest HDU (`find_jwst_data`).
- **(b)** JWST and HST products are multi-extension: `SCI`, `ERR`, `DQ`, `VAR_POISSON`, `VAR_RNOISE`, `VAR_FLAT`, `WCS`/`ASDF`; for `i2d` also `WHT` and `CON`. HST has `SCI`, `ERR`, `DQ` per chip (`EXTVER` 1, 2).
- **(c)** Read by `EXTNAME`. For JWST, use `stdatamodels`/`jwst.datamodels` (`ImageModel`), which also restores the GWCS. Represent images as `astropy.nddata.NDData`/`CCDData` with `uncertainty`, `mask`, `wcs` and `unit` attached.
- **(d)** Without `ERR` there are no uncertainties. Without `DQ`, saturated, hot and cosmic-ray-flagged pixels enter the measurements.
- **(e)** Low–medium.

### S3. Bandpass identification [I]
- **(a)** Uses `header['FILTER']` as the bandpass name, and as a dictionary key.
- **(b)**
  - **NIRISS** imaging records `FILTER=CLEAR` with the real bandpass in `PUPIL` (F090W, F115W, F150W, F200W…). The README's "Filter: CLEAR (broadband near-infrared)" is a misreading of exactly this.
  - **NIRCam** narrow and medium bands in the pupil wheel are paired with a filter-wheel element. For example F405N is `FILTER=F444W, PUPIL=F405N`. The code would label a Brackett-α narrow-band image as broadband F444W. That is the very filter used for NGC 3132, the README's flagship target.
  - Results keyed by the label overwrite each other. [verified]
- **(c)** A `Bandpass` resolver:
  - input: (`TELESCOP`, `INSTRUME`, `DETECTOR`, `FILTER`, `PUPIL`, `EXP_TYPE`);
  - output: a canonical bandpass with pivot wavelength, width and throughput curve;
  - sources: STScI throughput tables via `synphot`/`stsynphot`, or the SVO Filter Profile Service;
  - products keyed by `(obs_id, exposure, detector, bandpass)`.
- **(d)** Every colour, line map, SED and physical interpretation depends on knowing the bandpass.
- **(e)** Low–medium.

### S4. NaN handling [I]
- **(a)** `np.nan_to_num(…, nan=0)`.
- **(b)** In JWST `cal`/`i2d`, NaN marks `DO_NOT_USE` pixels or no coverage. Setting them to zero creates artificial holes and edges, biases background statistics, and makes Gaussian smoothing bleed zeros into real data.
- **(c)** Keep NaN. Build explicit boolean masks from NaN plus `DQ` bit flags (`stdatamodels.dqflags`) and pass `mask=` to photutils. Interpolate only for display.
- **(d)** Prevents spurious structure, and stops masked regions from distorting the background and noise estimates.
- **(e)** Low.

### S5. Background model [I]
- **(a)** One global sigma-clipped median, subtracted from the whole frame.
- **(b)**
  - A galaxy or nebula filling the field biases the median upward.
  - Real backgrounds vary spatially: zodiacal light, stray light ("wisps", "claws"), NIRCam 1/f striping, and MIRI's thermal background.
  - Stage-3 mosaics have already had sky matching applied, so a second global subtraction is unjustified.
- **(c)**
  - Product-appropriate background: leave Stage-3 sky as delivered and estimate local residual background in annuli for photometry.
  - For own processing: `photutils.background.Background2D` with iterative source masking and mesh size tied to source scale, plus the pipeline's 1/f-noise options for NIRCam.
  - Document the choice in provenance.
- **(d)** Background error is often the dominant systematic in extended-source and faint-source photometry.
- **(e)** Medium.

### S6. Clipping negative pixels to zero [I]: critical
- **(a)** `np.maximum(data - median, 0)`.
- **(b)** Background-subtracted sky noise is symmetric about zero. Clipping removes the negative half. The noise becomes half-normal, its mean is biased positive, and its σ is underestimated. Faint flux sums become biased because positive noise is kept and negative noise discarded. [verified] 50% of pure-noise pixels are clipped, giving 600 false detections.
- **(c)** Never modify science arrays for display reasons. Any clipping belongs inside the display stretch (`astropy.visualization`) and never touches measurement data.
- **(d)** This single line invalidates every downstream measurement.
- **(e)** Trivial.

### S7. Denoising before measurement; detection statistics [I]
- **(a)** Gaussian, median or TV denoising, then detection on the smoothed image. The threshold is `median + 3·std`, computed from that same smoothed, clipped image. Fixed `npixels=5`, no deblending.
- **(b)**
  - Smoothing correlates the noise. Its pixel σ is no longer the per-pixel noise, so "3σ" has no defined false-alarm rate.
  - TV and median filters are non-linear and do not conserve flux.
  - Measuring on smoothed data changes PSF-dependent fluxes and shapes.
- **(c)** Standard matched-filter detection:
  - convolve the data with a kernel approximating the PSF;
  - set the threshold from the **unconvolved** background RMS map (or the `ERR` array);
  - `detect_sources` + `deblend_sources`, with `n_pixels` tied to the PSF area;
  - measure on the **unsmoothed** data with `error=`.
- **(d)** Validate empirically:
  - **negative-image test** (detections on −data estimate the false-positive rate);
  - **injection–recovery** of artificial PSF sources (completeness vs magnitude).

  Without this, no source count, luminosity function or "new object" claim is defensible.
- **(e)** Medium.

### S8. Noise, uncertainty and signal-to-noise [N]
- **(a)** None. `SourceCatalog` has no `error` input, and S/N is never computed.
- **(b)** JWST provides `ERR` and the variance components. Drizzled/resampled `i2d` pixels have **correlated noise**, so per-pixel ERR underestimates the uncertainty of an aperture sum.
- **(c)**
  - Propagate `ERR` into aperture and segment photometry.
  - For resampled products, estimate aperture noise empirically: place random apertures on source-masked sky to measure σ(N_pix), then fit σ ∝ N^β.
  - Report S/N, and flag S/N < 5 measurements.
  - For own telescope data, use the full CCD equation ([04-observatory.md](04-observatory.md) §13.4).
- **(d)** A measurement without an uncertainty cannot be compared with anything, so it is not a measurement.
- **(e)** Medium; the correlated-noise treatment is **[R]**.

### S9. Units and photometric calibration [N]
- **(a)** Units are never read. "Flux" labels appear on normalised arrays.
- **(b)**
  - JWST `rate` is DN/s; `cal`/`i2d` are surface brightness in **MJy/sr**.
  - A point-source flux density needs ΣS·Ω_pix (`PIXAR_SR`) plus an aperture correction to total flux (APCORR reference data).
  - HST `flt`/`drz` are in e⁻ or e⁻/s and need `PHOTFLAM`/`PHOTFNU`/`PHOTPLAM`.
- **(c)**
  - Use `astropy.units.Quantity` end to end.
  - Use mission-specific photometric converters: AB mag = −2.5 log₁₀(f_ν / 3631 Jy).
  - Apply aperture corrections from instrument reference data.
- **(d)** Without units, comparison with catalogues, literature and other instruments is impossible.
- **(e)** Low–medium.

### S10. WCS, astrometry and reprojection [N]
- **(a)** `WCS(primary_header)` builds no celestial WCS. Plots are in pixels. The RGB is built by `np.stack` of raw arrays.
- **(b)**
  - Different detectors and instruments have different pixel grids: NIRCam SW 0.031″/px, LW 0.063″/px, MIRI 0.11″/px.
  - Stacking unaligned arrays is either an error (shape mismatch) or silently misregistered.
  - For `cal` files the accurate distortion model is the GWCS in the ASDF extension; the FITS SIP header is an approximation.
- **(c)**
  - `cal`: GWCS via datamodels. `i2d`: FITS WCS.
  - `reproject` for resampling: `reproject_exact` when flux conservation matters, `reproject_interp` for display.
  - `WCSAxes` for RA/Dec plots.
  - Astrometric validation against Gaia DR3 propagated to the observation epoch.
- **(d)** Cross-matching, multi-band colours, and comparing personal and professional data all depend on WCS.
- **(e)** Medium.

### S11. Display transform treated as data [I]
- **(a)** `enhance_contrast` normalises by global min/max, then the "enhanced" array feeds the RGB and is plotted with a "Flux" label.
- **(b)** A single hot pixel compresses the image into less than 1% of the range [verified, check 8]. Stretched arrays then propagate as if they were data.
- **(c)** Separate the **display layer** (interval + stretch at render time: `PercentileInterval`, `AsinhStretch`) from data. Colour composites use `make_lupton_rgb` (Lupton et al. 2004), with documented per-channel scaling and **chromatic ordering** (longest λ → red).
- **(d)** Prevents aesthetic choices from contaminating measurements, and makes colour images honest and reproducible.
- **(e)** Low.

### S12. RGB channel assignment [I]
- **(a)** The first three dictionary keys become R, G, B.
- **(b)** Channel order follows file order, not wavelength, so the colours carry no physical meaning.
- **(c)**
  - Sort by pivot wavelength.
  - Reproject onto a common grid.
  - Optionally PSF-match (`photutils.psf.matching.create_matching_kernel`) when colour gradients will be interpreted.
  - Record the mapping in provenance and label the image "representative colour".
- **(d)** Prevents colours being misread as physical, and makes the colour mapping documented and reproducible.
- **(e)** Low.

### S13. Exposures, detectors and associations [I]
- **(a)** One file is treated as "the image" of a target.
- **(b)**
  - NIRCam has 10 detectors (8 SW, 2 LW), and observations are dithered and mosaicked.
  - The JWST Stage-3 pipeline (`tweakreg`, `skymatch`, `outlier_detection`, `resample`) exists precisely to combine them.
  - A single `rate` file from one detector is a fragment.
- **(c)** Association-aware data model (ASN files, Level-3 products) that understands visits, exposures and detectors.
- **(d)** Image completeness, cosmic-ray rejection and the final noise level all depend on combining the exposures properly.
- **(e)** Medium.

### S14. Cosmic rays and artefacts [N]
- **(a)** Optional median filter only.
- **(b)** The artefacts are instrument-specific:
  - JWST: residual jumps; NIRCam snowballs, wisps and 1/f noise; MIRI cruciform; persistence.
  - HST: cosmic rays in single exposures; CTE trails (WFC3/UVIS, ACS/WFC).
- **(c)**
  - Rely on official pipeline steps (`jump`, `outlier_detection`; HST `flc` CTE-corrected products and AstroDrizzle CR rejection).
  - Use `astroscrappy`/L.A.Cosmic for single-exposure ground data.
  - Use instrument artefact flags in interpretation, so a wisp is never "a nebula".
- **(d)** Artefacts are the main source of false "discoveries".
- **(e)** Medium.

### S15. Observing mode [N]
- **(a)** All files are treated as 2-D images.
- **(b)** `EXP_TYPE` distinguishes `NRC_IMAGE`/`MIR_IMAGE`/`NIS_IMAGE` from spectroscopic modes (`NRS_MSASPEC`, `NRS_IFU`, `MIR_MRS`, `MIR_LRS-FIXEDSLIT`, `NIS_WFSS`, `NIS_SOSS`), coronagraphic modes and TSO modes. Processing a dispersed spectrum as an image is meaningless.
- **(c)** A mode router: unsupported modes are refused explicitly, never processed silently.
- **(d)** Prevents nonsense outputs from spectroscopic, coronagraphic and time-series data.
- **(e)** Low.

### S16. Global warning suppression [I]
- **(a)** `warnings.filterwarnings('ignore')` in four modules.
- **(b)** It hides `FITSFixedWarning`, unit-parse failures and deprecation warnings, which are exactly the signals that metadata is wrong.
- **(c)** Log warnings. Filter only specific, understood warnings, with a comment explaining each.
- **(d)** Metadata and unit problems surface instead of passing silently into results.
- **(e)** Trivial.

### S17. Data selection and provenance of the "real data" claim [I]
- **(a)** Downloads the first row of `Observations.query_criteria(obs_collection='JWST')`.
- **(b)**
  - The observation is arbitrary: it may be calibration or engineering data, and is unrelated to any science question.
  - The README calls program 01063 "Early Release Science". The JWST ERS programs have IDs in the 1288–1386 range, so 1063 is **not** one of them.
  - Its actual category should be checked on the STScI program information page. That page was not reachable from the audit environment, so this report does not assert one.
- **(c)** Explicit discovery: target resolution, then constraint-based search, then a ranked candidate list with program, PI, instrument, mode, bandpass and exposure time. Record the chosen `obs_id` and product URI.
- **(d)** Scientific claims must be traceable to specific, intended data.
- **(e)** Low.

### S18. Fabricated metadata [I]: critical
- **(a)** `jwst_real_data_demo.py` downloads `jw02756001001_02101_00001_nrca1_rate.fits` and `…00002_nrca1_rate.fits` and saves them as `NGC_3132_F444W.fits` and `NGC_3132_F277W.fits`.
- **(b)** All three labels are wrong:
  - **Program 2756** is DDT imaging of Abell 2744 following up a supernova found in GLASS NIRISS data (Chen et al.).
  - **NGC 3132** is ERO program 2733, observed with F090W, F187N, F212N, F356W, F405N and F470N; it has no F444W.
  - **NRCA1** is a short-wavelength (0.6–2.3 µm) detector, so it cannot record F444W or F277W.
- **(c)** Never rename archive files. Derive every label from headers and archive metadata, and keep the original filename as the primary key.
- **(d)** This is precisely the "never invent telescope metadata" failure the target system must prevent.
- **(e)** Trivial.

### S19. Synthetic content presented as JWST output [I]
- **(a)** The README hero image is made by `create_sample_visualization.py` from a synthetic spiral plus Poisson "stars". Its "RGB composite" is `np.roll` of one image by 10 and 20 rows.
- **(b)** It is presented as "Sample JWST Processing".
- **(c)** Label it as synthetic, or replace it with a properly processed real `i2d` with a documented provenance record.
- **(d)** Readers are not misled into treating synthetic output as JWST results.
- **(e)** Trivial.

### Assumptions not made but needed (instrument-specific)
None of these are implemented. The research platform needs all of them:
- PSF models: STPSF, formerly WebbPSF.
- Saturation and non-linearity flags.
- Brighter-fatter effect.
- Persistence.
- Aperture corrections.
- Time standards: `MJD-BEG`/`MJD-AVG` in TDB vs UTC (important for time-domain work).
- Parallax and proper-motion epochs for cross-matching.

---

## 5. Critical problems (ranked)

| Rank | Problem | Consequence | Fix effort |
|-----:|---------|-------------|-----------|
| 1 | Negative clipping and an invalid detection threshold (S6, S7) | Catalogues dominated by false sources | Hours |
| 2 | Fabricated target and filter names in `jwst_real_data_demo.py` (S18) | Provenance corrupted at the source | Minutes |
| 3 | Main pipeline cannot load JWST MEF files (S2) | Main CLI is unusable on real data | Hours |
| 4 | Bandpass mislabelling and overwriting (S3) | Wrong physics attached to images; data silently lost | Days |
| 5 | No units, uncertainties or masks (S8, S9, S4) | No measurement is comparable or reproducible | 1–2 weeks |
| 6 | Wrong product level and untargeted download (S1, S17) | "Real data" is uncalibrated and arbitrary | Days |
| 7 | Broken visualiser and missing `astroquery` dependency | Fresh install cannot reproduce the README | Hours |
| 8 | README overclaims and synthetic hero image (S19) | Misleads readers about capability | Hours |
| 9 | No tests, no packaging, no persistence | Every later phase would be built on sand | 1 week to set up |

---

## 6. Immediate improvements (Phase 0, roughly 1–2 weeks part-time)

These make the repository **honest and installable** before any new capability is added.

1. **Freeze the legacy code.** Move the nine scripts to `legacy/`, unchanged, plus a short README
   explaining that they are kept for comparison and are known to be scientifically invalid
   (link to this audit).
2. **Fix the README.**
   - Remove "publication-quality", "complete pipeline" and the unsupported-instrument claims.
   - Label the hero image as synthetic.
   - Link to `docs/lab-roadmap/`.
3. **Correct the provenance errors.** Delete the renaming in `jwst_real_data_demo.py` (or delete the
   script), and correct the program-01063 "ERS" statement.
4. **Create a package skeleton:** `pyproject.toml`, `src/astrolab/` (working name; check PyPI
   availability before publishing), `uv.lock`, Python ≥ 3.11, `ruff`, `pytest`, GitHub Actions running
   offline tests.
5. **Write the first core types and tests:**
   - `io.open_product(path)`: reads MEF by `EXTNAME`; returns an `NDData` subclass carrying `SCI`, `ERR`, `DQ`-mask, `unit`, WCS and header.
   - `Bandpass.from_header(header)`: handles NIRISS `PUPIL` and NIRCam pupil-wheel pairs.
   - Display stretch functions that **never mutate data**.
6. **Turn the audit into regression tests.** [`audit_checks.py`](audit_checks.py) becomes the seed
   of `tests/test_science_invariants.py`:
   - "detections on pure noise ≤ expected false-positive count";
   - "background subtraction preserves zero-mean noise";
   - "three NIRISS bands give three products".
7. **Add provenance v0.** Every saved output gets a sidecar JSON with:
   - input file SHA-256, `obs_id`, product URI;
   - `CAL_VER`, `CRDS_CTX`;
   - package versions, git commit, parameters, timestamp.
8. **Add `CLAUDE.md` and a SessionStart hook** so cloud sessions (including from the iPad app) start
   with dependencies installed and the scientific rules loaded. *(Done in this commit.)*
