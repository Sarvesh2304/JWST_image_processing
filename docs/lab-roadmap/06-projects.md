# Part 6: Project Portfolio and MSc/PhD-Level Research Opportunities

> Report sections covered: **23** Beginner/intermediate/advanced/research projects · **24** MSc/PhD-level opportunities.
>
> Every project is designed to **build a platform component** while teaching something, so learning and
> building are the same activity. Effort assumes one person part-time (~10–15 h/week). "Platform" says
> which module the project creates or validates.

Rating scales: Difficulty 1–5 · Scientific value 1–5 · Publication potential: none / note (RNAAS, JAAVSO, MPB) / paper / software paper (JOSS, A&C).

---

## 23.1 Beginner: fundamentals of astrophysics and computation

### B1. From MJy/sr to magnitudes: photometry of stars in a JWST mosaic
- **Question:** Do my aperture magnitudes of stars in a NIRCam `i2d` agree with the pipeline catalogue?
- **Motivation:** Units, apertures and uncertainties are the base of every later measurement.
- **Data / source:** One public NIRCam Stage-3 `i2d` + `_cat.ecsv` (MAST).
- **Theory:** Surface brightness vs flux density, pixel solid angle, AB system, aperture corrections, Poisson and background noise.
- **Method:** Read `SCI`/`ERR`/`DQ`; aperture photometry with errors; convert with `PIXAR_SR`; compare with the catalogue; plot residuals vs magnitude.
- **Tools:** astropy, photutils, astroquery.
- **Output:** Validated notebook plus the first science test in `tests/science/`.
- **Difficulty / effort:** 2 / 1–2 weeks. **Value:** 2. **Publication:** none.
- **Platform:** `io`, `photometry`, `missions/jwst` (Phase 1 acceptance test).

### B2. What does each filter see? Bandpasses vs physical spectra
- **Question:** Which emission mechanisms dominate NIRCam F200W, F335M, F444W and MIRI F770W, F2100W for stars, H II regions and dusty galaxies?
- **Motivation:** You cannot interpret an image without knowing what physics the bandpass samples.
- **Data / source:** STScI throughput curves; template spectra (blackbodies, a PAH template, stellar libraries).
- **Theory:** Planck law, dust emission, PAH features (3.3, 7.7, 11.3 µm), recombination lines (Paα, Brα).
- **Method:** Synthetic photometry of templates through each bandpass; colour–colour diagrams.
- **Tools:** synphot/stsynphot, astropy.
- **Output:** Notebook + the `Bandpass` resolver's physical metadata (lines and features in band).
- **Difficulty / effort:** 2 / 1 week. **Value:** 2. **Publication:** none.
- **Platform:** `core.Bandpass`, `interpret` (feeds L2 rules).

### B3. An HR diagram from Gaia
- **Question:** What are the age and distance of the Pleiades and M67 from Gaia DR3 alone?
- **Motivation:** Stellar evolution in one figure; parallax inference done properly.
- **Data / source:** Gaia DR3 (ESA archive TAP); MIST isochrones.
- **Theory:** Parallax and its biases (zero-point offset), extinction, isochrones.
- **Method:** ADQL query, membership via PM/parallax clustering, CMD, isochrone fit (MCMC).
- **Tools:** astroquery.gaia, emcee.
- **Output:** Notebook; ages/distances vs literature (cited).
- **Difficulty / effort:** 2 / 2 weeks. **Value:** 2. **Publication:** none.
- **Platform:** `archives/esa/gaia`, inference utilities.

### B4. Orbits that you can check
- **Question:** How well does an N-body integration of the Solar System reproduce JPL Horizons ephemerides over 10 years?
- **Motivation:** Numerical integration, energy conservation, error growth.
- **Data / source:** JPL Horizons (initial conditions and truth).
- **Theory:** Kepler problem, symplectic integrators, perturbations.
- **Method:** REBOUND with WHFast vs IAS15; compare positions; study timestep dependence.
- **Tools:** REBOUND, astroquery.jplhorizons.
- **Output:** Notebook; a `simulation` wrapper.
- **Difficulty / effort:** 2 / 1 week. **Value:** 1. **Publication:** none.
- **Platform:** `simulation`, `archives/horizons`.

### B5. Measure your detector, honestly: injection–recovery
- **Question:** What are the completeness and false-positive rate of my source detection as a function of magnitude?
- **Motivation:** Directly fixes the audit's central problem. Every survey reports this.
- **Data / source:** A real `i2d` (B1) + synthetic PSF sources (STPSF).
- **Theory:** Matched filtering, false-alarm probability, completeness functions.
- **Method:** Inject N sources per magnitude bin; detect; match; negative-image test.
- **Tools:** photutils, STPSF, GalSim (optional).
- **Output:** Completeness curves; regression tests.
- **Difficulty / effort:** 3 / 2 weeks. **Value:** 2. **Publication:** none.
- **Platform:** `imaging.detection` validation (Phase 2 acceptance).

### B6. Your first light curve
- **Question:** What is the period and transit depth of a known TESS planet, and how precisely can I measure them?
- **Motivation:** Time-domain fundamentals before using your own telescope.
- **Data / source:** TESS SPOC light curves (MAST).
- **Theory:** Transit geometry, limb darkening, BLS periodogram.
- **Method:** lightkurve → detrend → BLS → transit fit (batman + emcee).
- **Tools:** lightkurve, astropy.timeseries, batman, emcee.
- **Output:** Notebook; `timedomain` module seed.
- **Difficulty / effort:** 2 / 1–2 weeks. **Value:** 1. **Publication:** none.
- **Platform:** `timedomain`, `archives/mast` (TESS).

---

## 23.2 Intermediate: real datasets

### I1. Astrometric truth test: JWST/HST mosaics vs Gaia
- **Question:** What are the astrometric residuals of public JWST/HST Stage-3 mosaics relative to Gaia DR3 propagated to the observation epoch?
- **Motivation:** Every cross-match in the platform depends on this.
- **Data / source:** Several `i2d`/`drc` files; Gaia DR3.
- **Theory:** WCS, distortion, proper-motion propagation, systematic vs random errors.
- **Method:** Detect stars → match Gaia (epoch-propagated) → residual vector fields → fit offsets/rotation.
- **Tools:** astropy, photutils, astroquery.
- **Output:** Per-image astrometric quality report (shown automatically in "What am I looking at?").
- **Difficulty / effort:** 3 / 2–3 weeks. **Value:** 2. **Publication:** note possible if systematic offsets are found.
- **Platform:** `astrometry`, `crossmatch`.

### I2. NGC 3132 emission-line structure with NIRCam narrow bands
- **Question:** How do the H₂ (F212N, F470N), Paα (F187N) and Brα (F405N) emission distributions differ, and what does that say about ionised vs molecular gas?
- **Motivation:** Corrects the original project's flagship target with correct bandpass handling.
- **Data / source:** JWST ERO program **2733** (MAST); continuum from F090W/F356W.
- **Theory:** Recombination lines, H₂ excitation, continuum subtraction, extinction (line ratios).
- **Method:** Reproject → continuum-subtract narrow bands → line maps → radial and azimuthal profiles; compare with De Marco et al. 2022 (Nature Astronomy 6, 1421).
- **Tools:** reproject, photutils, PyNeb (later).
- **Output:** Line maps with provenance; comparison figure.
- **Difficulty / effort:** 3 / 3–4 weeks. **Value:** 2. **Publication:** none (reproduction); the RNAAS-level extension is A6.
- **Platform:** `imaging.reproject`, multi-band products, `interpret` (nebula rules).

### I3. A multi-wavelength SED of a nearby galaxy
- **Question:** What fraction of M51's (or NGC 628's) luminosity is reprocessed by dust?
- **Motivation:** Multi-mission integration with consistent apertures and PSFs.
- **Data / source:** GALEX (MAST), SDSS/Legacy Surveys, 2MASS/WISE (IRSA), JWST/HST where covered.
- **Theory:** Stellar populations, dust attenuation and emission, energy balance.
- **Method:** PSF-matched aperture photometry across bands; SED fitting (e.g. CIGALE or Prospector).
- **Tools:** reproject, photutils PSF matching, astroquery, SED code.
- **Output:** SED with uncertainties and provenance.
- **Difficulty / effort:** 3 / 4 weeks. **Value:** 2. **Publication:** none.
- **Platform:** comparison engine (§14.5), multi-archive adapters.

### I4. Transit ephemeris refinement
- **Question:** How much has the predicted transit time of a selected TESS planet drifted, and what is the updated ephemeris?
- **Motivation:** Stale ephemerides are a genuine problem for future atmospheric missions (Ariel). Amateur data helps.
- **Data / source:** TESS (MAST), ExoClock/ETD published times.
- **Theory:** Linear ephemeris, error propagation, TTVs.
- **Method:** Fit individual transits → O−C diagram → weighted linear fit.
- **Tools:** lightkurve, batman, emcee.
- **Output:** Updated ephemeris + a target list for your telescope.
- **Difficulty / effort:** 3 / 2–3 weeks. **Value:** 3. **Publication:** note-level, possibly contributing to ExoClock.
- **Platform:** `timedomain`, `planning` (feeds transit predictions).

### I5. Variable stars from surveys: period–luminosity relations
- **Question:** Can I recover the RR Lyrae or Cepheid period–luminosity relation from ZTF and Gaia data?
- **Motivation:** The distance ladder, built with your own pipeline.
- **Data / source:** ZTF light curves (IRSA), Gaia DR3 variability and parallaxes.
- **Theory:** Pulsation, P–L relations, extinction.
- **Method:** Lomb–Scargle periods → P–L fit with errors-in-variables.
- **Tools:** astropy.timeseries, astroquery.
- **Output:** Notebook; periodogram tools.
- **Difficulty / effort:** 3 / 3 weeks. **Value:** 2. **Publication:** none.
- **Platform:** `timedomain`, `archives/irsa`.

### I6. Moving objects in archival images
- **Question:** Which catalogued asteroids cross a set of archival frames, and can I measure their positions to MPC standards?
- **Motivation:** Prepares the astrometry pipeline for your telescope.
- **Data / source:** Pan-STARRS or ZTF frames; SkyBoT; Horizons.
- **Theory:** Ephemerides, light-travel time, topocentric corrections.
- **Method:** SkyBoT cone search at exposure mid-time → detect → astrometry vs Gaia → compare with Horizons.
- **Tools:** astroquery (Skybot, Horizons), photutils.
- **Output:** ADES-format astrometry export (validated against the MPC schema).
- **Difficulty / effort:** 3 / 3 weeks. **Value:** 2. **Publication:** none.
- **Platform:** `astrometry`, `archives/mpc`.

---

## 23.3 Advanced: sophisticated analysis, simulation, ML, multi-mission

### A1. Crowded-field PSF photometry of resolved stars with JWST
- **Question:** Can I reproduce published CMDs of a nearby dwarf galaxy from JWST ERS 1334 (Resolved Stellar Populations) data?
- **Data / source:** ERS 1334 NIRCam data (MAST); published DOLPHOT-based catalogues for comparison.
- **Theory:** PSF photometry, crowding, artificial-star tests, CMD interpretation.
- **Method:** STPSF/empirical PSF → photutils iterative PSF photometry → artificial stars → CMD vs isochrones.
- **Tools:** photutils.psf, STPSF.
- **Output:** CMD, completeness, comparison with literature.
- **Difficulty / effort:** 4 / 2 months. **Value:** 3. **Publication:** note (method comparison).
- **Platform:** `photometry.psf`.

### A2. Dust-obscured star formation in nearby spirals
- **Question:** How does mid-IR emission (MIRI F770W, F2100W) trace star formation relative to Hα and UV in PHANGS galaxies?
- **Data / source:** PHANGS-JWST (GO 2107) and PHANGS-HST high-level products (MAST HLSPs); GALEX.
- **Theory:** SFR tracers, PAH physics, dust heating.
- **Method:** Reproduce a published resolved SFR calibration, then extend it to galaxies or regions not in the original analysis.
- **Tools:** reproject, photutils, statistics.
- **Output:** Reproduction + extension.
- **Difficulty / effort:** 4 / 2–3 months. **Value:** 3. **Publication:** note; paper with collaborators.
- **Platform:** multi-band analysis, HLSP adapters, RO-Crate export.

### A3. Strong-lens modelling of a JWST cluster arc
- **Question:** Do independent models of SMACS J0723 predict consistent magnifications for a chosen arc?
- **Data / source:** JWST ERO SMACS 0723 (MAST); published models (cite the specific papers retrieved).
- **Theory:** Lensing potential, magnification, degeneracies.
- **Method:** lenstronomy model of a single system; compare with published magnification maps.
- **Tools:** lenstronomy.
- **Output:** Model + uncertainty comparison.
- **Difficulty / effort:** 5 / 3 months. **Value:** 2. **Publication:** note.
- **Platform:** `simulation`, interpretation rules for "lens" claims (L2 requires a model).

### A4. Morphology classifier under domain shift
- **Question:** How well does a Galaxy-Zoo-trained classifier (e.g. Zoobot) transfer from Legacy Surveys to Euclid Q1 and to your own telescope's images?
- **Data / source:** Legacy Surveys cutouts, Euclid Q1 (ESA), Galaxy Zoo labels; own images later.
- **Theory:** CNNs, calibration, domain adaptation.
- **Method:** Evaluate a pretrained model; measure calibration; fine-tune; compare across PSF and depth regimes.
- **Tools:** PyTorch, Zoobot.
- **Output:** Model card + evaluation.
- **Difficulty / effort:** 4 / 2 months. **Value:** 2. **Publication:** note.
- **Platform:** `ml` (first model with a model card).

### A5. Globular-cluster orbits and the Milky Way potential
- **Question:** How sensitive are inferred GC orbits (pericentres, energies) to the choice of Galactic potential?
- **Data / source:** Gaia-based GC kinematics (Vasiliev & Baumgardt 2021 catalogue via VizieR).
- **Theory:** Galactic dynamics, actions, potentials.
- **Method:** galpy/gala orbits in multiple potentials with Monte Carlo error propagation.
- **Tools:** galpy, gala.
- **Output:** Orbit catalogue with uncertainties.
- **Difficulty / effort:** 3 / 1–2 months. **Value:** 2. **Publication:** note.
- **Platform:** `simulation`, VizieR adapter.

### A6. Photoionisation model of a planetary nebula
- **Question:** Can a CLOUDY model reproduce JWST + ground-based line ratios of NGC 3132's inner nebula?
- **Data / source:** I2 line maps; published optical spectra (VizieR or literature).
- **Theory:** Photoionisation equilibrium, nebular diagnostics.
- **Method:** PyNeb diagnostics → CLOUDY grid → compare.
- **Tools:** CLOUDY, PyNeb.
- **Output:** Model with parameter uncertainties.
- **Difficulty / effort:** 4 / 2–3 months. **Value:** 3. **Publication:** possible note.
- **Platform:** `simulation` ↔ data comparison contract.

---

## 23.4 Research-grade: MSc / PhD preparation, publications, open-source, collaborations

### R1. Long-term exoplanet ephemeris and TTV monitoring (own telescope + TESS)
- **Question:** Do selected warm and hot Jupiters show transit-timing variations or orbital decay over a 5–10-year baseline?
- **Motivation:** Ephemeris maintenance for Ariel/JWST scheduling; orbital decay is a live research topic.
- **Data / source:** Own transits (configuration A/B), TESS, ExoClock/ETD archives.
- **Theory:** Tidal decay, TTVs, timing systematics (BJD_TDB).
- **Method:** Standardised reduction (Gaia XP-calibrated comparisons), MCMC transit fits, O−C modelling with model comparison.
- **Tools:** Platform `timedomain` + `observatory`.
- **Output:** Timing database; contributions to ExoClock.
- **Difficulty / effort:** 3 (sustained) / years. **Value:** 4. **Publication:** **papers** (collaboration papers; first-author note).
- **Platform:** End-to-end showcase: plan → observe → reduce → publish.

### R2. Low-surface-brightness tidal features around nearby galaxies
- **Question:** What fraction of nearby Milky-Way-mass galaxies show tidal features brighter than ~27–28 mag/arcsec², compared with ΛCDM predictions?
- **Motivation:** Hierarchical assembly; amateur-scale telescopes have contributed (Martínez-Delgado et al. 2010).
- **Data / source:** Own deep imaging (configuration B/C, dark site), Legacy Surveys for comparison, IllustrisTNG stellar haloes (public).
- **Theory:** Accretion, stellar haloes, surface-brightness limits.
- **Method:** Careful flat-fielding, sky modelling, depth measurement, injection of mock streams, classification.
- **Tools:** Platform `calibration`, `imaging`, `simulation` (mock streams).
- **Output:** Catalogue of features with detection limits.
- **Difficulty / effort:** 4 / 1–3 years. **Value:** 4. **Publication:** **paper** (with collaborators).
- **Platform:** Own-telescope + professional comparison engine.

### R3. Spectroscopic monitoring of Be stars or symbiotic binaries
- **Question:** How do Hα equivalent width and V/R ratios evolve through disc build-up and dissipation cycles in selected Be stars?
- **Data / source:** Own R≈1000–10 000 spectra (configuration B/C), BeSS/ARAS archives, TESS photometry.
- **Theory:** Decretion discs, line formation.
- **Method:** Standardised reduction (specreduce), wavelength and telluric correction, time-series analysis.
- **Output:** Contributions to BeSS/ARAS; analysis paper with professional partners.
- **Difficulty / effort:** 4 / years. **Value:** 4. **Publication:** **paper**.
- **Platform:** `spectroscopy` module.

### R4. Evidence-graded image interpretation: open-source software + benchmark
- **Question:** Can a deterministic evidence engine plus an LLM renderer explain astronomical images with zero fabricated identifications, measured on a public benchmark?
- **Motivation:** AI reliability in science is an open problem; your platform's core idea is publishable.
- **Data / source:** Benchmark of real JWST/HST/ground images with curated ground truth (SIMBAD/NED identities, known artefacts).
- **Method:** Release `interpret` as a package; define metrics (fabrication rate, level-promotion errors, citation validity); compare LLM-only baselines.
- **Output:** Package + benchmark.
- **Difficulty / effort:** 4 / 6–12 months. **Value:** 3. **Publication:** **JOSS** or *Astronomy and Computing* (software paper); workshop paper.
- **Platform:** `interpret`, `assistant`, evaluation suite.

### R5. Variability and transients in multi-epoch JWST deep fields
- **Question:** What variable or transient sources exist in JWST fields observed at multiple epochs, after rigorous artefact rejection?
- **Motivation:** JWST deep fields have repeat coverage; published transient searches (e.g. in JADES) show the potential.
- **Data / source:** Public multi-epoch NIRCam data (MAST).
- **Theory:** Difference imaging, SN rates at high z, AGN variability.
- **Method:** PSF-matched difference imaging, real/bogus classifier, injection tests.
- **Output:** Candidate catalogue (L3 → L2 with evidence).
- **Difficulty / effort:** 5 / 6–12 months. **Value:** 4. **Publication:** **paper** (needs careful novelty check against the literature).
- **Platform:** `timedomain.difference`, `ml` real/bogus.

### R6. Asteroid rotation periods and phase curves for under-observed objects
- **Question:** What are the rotation periods and phase-curve parameters of selected asteroids lacking reliable lightcurves?
- **Data / source:** Own photometry; Gaia DR3 Solar System object photometry; ALCDEF database.
- **Theory:** Lightcurve inversion, phase functions (H, G₁, G₂).
- **Method:** Multi-night differential photometry with light-time correction; period search; phase fits.
- **Output:** ALCDEF submissions; **Minor Planet Bulletin** papers (an established amateur–professional venue).
- **Difficulty / effort:** 3 / months per object set. **Value:** 3. **Publication:** **MPB notes**.
- **Platform:** `astrometry`, `photometry.differential`, `planning`.

### R7. Occultation timing campaigns
- **Question:** Shape and size constraints of asteroids from multi-chord occultations.
- **Data / source:** Own high-cadence video or CMOS with GPS timing; IOTA predictions.
- **Method:** Timing extraction with uncertainty; chord submission.
- **Output:** Contributions to IOTA/IOTA-ES results.
- **Difficulty / effort:** 3. **Value:** 4 per positive chord. **Publication:** collaboration papers.
- **Platform:** `observatory` timing, `planning`.

---

## 24. MSc/PhD-level research opportunities: how to use this platform as preparation

| Opportunity | Why it is research-grade | Skills it demonstrates to supervisors | Realistic outcome |
|-------------|--------------------------|---------------------------------------|-------------------|
| R1 ephemerides / TTVs | Real open problem (orbital decay, Ariel scheduling); sustained dataset | Photometry, timing, Bayesian inference, observing | Collaboration paper(s); MSc thesis core |
| R2 LSB features | Tests galaxy formation; known amateur precedent | Systematics control, image processing, simulation comparison | Paper with professional collaborators |
| R4 evidence engine | Novel at the AI–science interface | Software engineering, evaluation design, astronomy knowledge | JOSS/A&C paper; strong PhD application signal |
| R5 JWST transients | Exploits public data; competitive area | Difference imaging, ML, statistics | Paper if novelty holds (check the literature first) |
| A2 dust-obscured SF | Reproduction then extension of a Treasury programme | Multi-wavelength analysis, careful reproduction | Note or paper; good MSc project |
| R3 spectroscopy | Long-term monitoring niche where professionals lack telescope time | Spectroscopic reduction, astrophysical modelling | Pro-am paper |

How to make these PhD-preparation-grade:
1. Write a one-page proposal per project (question, hypothesis, data, method, feasibility, risks). The assistant's §15.4 template produces the draft.
2. Pre-register the analysis plan in the project journal before looking at results.
3. Release code and data products with DOIs (Zenodo) via the RO-Crate export.
4. Seek a professional collaborator early. Amateur data plus professional context is how these projects get published.
5. Publish small first: RNAAS, JAAVSO and MPB notes are legitimate, peer-reviewed or moderated outlets that build a record.
