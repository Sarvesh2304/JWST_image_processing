# Part 3: Real Data, JWST/HST, Multi-Mission Integration, and the Scientific-Analysis Engine

> Report sections covered: **8** Real-data architecture · **9** JWST/HST integration ·
> **10** Multi-mission integration · **14** Scientific-analysis engine (including "What am I looking at?",
> object identification/cross-matching, and combining personal data with professional data).
>
> Facts about data releases were checked on 2026-10-06. Archives change, so the platform should read
> service capabilities at run time (VO `capabilities`/`tables` endpoints) rather than hard-coding them.

---

## 8. Real-data architecture

### 8.1 Flow

```
User question ("JWST images of nearby spiral galaxies")
   │
   ▼
Intent → structured query            (assistant drafts; user can edit)
   │     {object_class, region|names, λ-range, resolution, product_level, public_only}
   ▼
Name / region resolution             Sesame (CDS) → SIMBAD/NED; JPL Horizons for Solar-System bodies
   │
   ▼
Coverage discovery (cheap)           CDS MOCServer: "which collections cover this position?"
   │                                 ObsCore TAP across MAST, ESA, IRSA, HEASARC, ALMA, NOIRLab
   ▼
Candidate ranking                    by bandpass, resolution, depth (t_exp), calib_level, data rights
   │                                 → shown to the user as a table, not silently chosen
   ▼
Mission adapter: list products       mission-specific product semantics (level, type, association)
   │
   ▼
Retrieval → local cache              checksums, resumable, cloud (S3) when available
   │
   ▼
Reader → typed product               ImageProduct / SpectrumProduct / CubeProduct / TimeSeries / Catalog
   │                                 with unit, uncertainty, mask, WCS, bandpass, provenance
   ▼
Science engine → measurements → evidence → interpretation
```

### 8.2 Use VO standards as the common layer, and adapters for what VO cannot express

| Standard | Use in the platform |
|----------|---------------------|
| **TAP + ADQL** | Uniform metadata queries: MAST CAOM/ObsCore, Gaia archive, ESA archives, IRSA, HEASARC, ALMA, CDS (SIMBAD TAP, VizieR TAP) |
| **ObsCore** | Common observation description (`obs_collection`, `instrument_name`, `em_min/em_max`, `s_region`, `t_exptime`, `calib_level`, `access_url`). This is the right **discovery schema** for the internal index. |
| **SIA v2 / SSA / SCS** | Image, spectrum and cone searches where TAP is overkill |
| **DataLink** | Find related files (previews, cutouts, calibration) for a dataset |
| **MOC** | Fast coverage tests and footprint intersection ("which surveys cover my field") |
| **HiPS / hips2fits** | Quick-look images across surveys on a common grid. **Display and context only**: HiPS tiles are resampled and not meant for precise photometry. |
| **VOTable / SAMP** | Interchange with TOPCAT, Aladin and DS9 |
| **IVOA Provenance DM** | Model for our provenance records |

The VO layer gives uniform discovery but **not** uniform science semantics. Mission adapters
supply what VO does not standardise:
- product levels and associations;
- units conventions (MJy/sr vs e⁻/s vs counts vs Jy/beam);
- calibration pipelines and reference data;
- known artefacts and data rights.

### 8.3 MissionAdapter contract

```python
class MissionAdapter(Protocol):
    name: str                                    # "MAST:JWST", "ESA:Gaia", "CXC:Chandra", ...
    def search(self, where: SkyRegion | str, *, bands=None, modes=None,
               levels=None, public_only=True, limit=200) -> ObservationTable: ...
    def products(self, obs: ObservationRecord, *, level=None,
                 kinds=("science",)) -> ProductTable: ...
    def fetch(self, product: ProductRecord, *, cache: Store,
              prefer_cloud=True) -> LocalFile: ...          # checksum verified, provenance recorded
    def open(self, f: LocalFile) -> Product: ...             # mission-aware reader
    def calibration_context(self, f: LocalFile) -> dict: ... # pipeline version, reference context
    def known_systematics(self, product: Product) -> list[Caveat]: ...
```

### 8.4 Internal representation, by data kind

The representation stays faithful to how each measurement is made.

| Kind | Internal type | Notes on mission-specific semantics |
|------|---------------|-------------------------------------|
| Optical/IR image | `ImageProduct` (NDData: data, uncertainty, mask, wcs/gwcs, unit, bandpass) | Surface brightness (JWST MJy/sr) vs count rate (HST e⁻/s) vs ADU (own camera) |
| X-ray | **Event list** (`EventList`: time, position, energy/PI per photon) + derived images with exposure maps | Poisson statistics. Energy-dependent PSF. Spectra need response files (ARF/RMF) and CIAO/SAS. An X-ray "image" is a binning choice. |
| Radio interferometry (ALMA) | `ImageProduct` in Jy/beam + `beam` + `max_recoverable_scale`; cubes as `CubeProduct` | Missing short spacings resolve out extended flux. The units are per beam, not per pixel. |
| Spectra | `SpectrumProduct` (specutils `Spectrum`) with spectral axis, flux unit, uncertainty, LSF/resolution | Slit, fibre, IFU-extracted and slitless spectra each have different systematics |
| Cubes | `CubeProduct` (spectral-cube) | JWST NIRSpec/MIRI IFU `s3d`, ALMA cubes |
| Time series | `TimeSeries` (astropy) / lightkurve `LightCurve` with time scale (TDB/BJD) | Barycentric correction is mandatory for timing science |
| Catalogues | `Catalog` (astropy Table ↔ Parquet) with column units, UCDs, epoch, reference system | Gaia positions are at epoch J2016.0; other catalogues use other epochs |

Formats: FITS (MEF, BINTABLE), **ASDF** (JWST GWCS; Roman's native format), VOTable, HDF5
(simulations, some surveys), Parquet (Rubin and large catalogues), CSV/ECSV (ECSV preferred, because it
keeps units). JPEG/PNG are **never** measured. If a PNG carries **AVM** (Astronomy Visualization
Metadata) or can be plate-solved, its WCS can be used for *identification only*.

### 8.5 Archive priority (scored for this platform)

Scale for each criterion: 1 (low) to 3 (high).

| Archive / service | Sci. value | API | Access | Relevance to user | Difficulty (3 = easy) | Fit | **Tier** |
|-------------------|:--:|:--:|:--:|:--:|:--:|:--:|:--:|
| **MAST**: JWST, HST, TESS, Kepler/K2, Pan-STARRS, GALEX, HLSPs | 3 | 3 | 3 | 3 | 2 | 3 | **1** |
| **CDS**: Sesame, SIMBAD, VizieR, XMatch, hips2fits, MOCServer | 3 | 3 | 3 | 3 | 3 | 3 | **1** |
| **Gaia** (ESA archive, TAP; DR3 now, **DR4 planned 2 Dec 2026**) | 3 | 3 | 3 | 3 | 3 | 3 | **1** |
| **NASA ADS/SciX + arXiv** (literature) | 3 | 3 | 3 | 3 | 3 | 3 | **1** |
| **JPL Horizons / SBDB, IMCCE SkyBoT, MPC** (Solar System) | 2 | 3 | 3 | 3 | 3 | 3 | **1** (needed for own telescope) |
| **IRSA**: 2MASS, AllWISE/unWISE, Spitzer, **ZTF** | 3 | 3 | 3 | 2 | 3 | 3 | **2** |
| **NOIRLab Astro Data Lab / Legacy Surveys** (deep optical imaging and catalogues) | 3 | 3 | 3 | 3 | 2 | 3 | **2** |
| **SDSS** (DR20 released July 2026) | 3 | 2 | 3 | 2 | 2 | 2 | **2** |
| **AAVSO** (VSX, data, campaigns), **TNS**, **NED** | 2 | 2 | 3 | 3 | 3 | 3 | **2** |
| **Chandra** (CXC; Chandra Source Catalog) | 3 | 2 | 3 | 2 | 1 | 2 | **3** |
| **XMM-Newton** (XSA; 4XMM catalogue) | 3 | 2 | 3 | 2 | 1 | 2 | **3** |
| **ALMA** Science Archive | 3 | 2 | 3 | 2 | 1 | 2 | **3** |
| **Euclid** (Q1 public since Mar 2025; **DR1-Foundation planned Nov 2026**, full DR1 mid-2027) | 3 | 2 | 3 | 2 | 2 | 2 | **3** (after DR1-Foundation) |
| **ESO** Science Archive (Phase 3 products, MUSE cubes) | 3 | 2 | 3 | 2 | 2 | 2 | **3** |
| **Rubin/LSST**: **alerts** via brokers (public since Feb 2026; ALeRCE, Fink, Lasair, ANTARES, AMPEL, Pitt-Google, Babamul) | 3 | 2 | 3 | 2 | 2 | 2 | **3** (alerts) |
| **Rubin images/catalogues** (EDP2 July 2026, DP2 late 2026) | 3 | 2 | **1** | 2 | 2 | 2 | **4**: needs data rights (US/Chile and in-kind contributors). Check your eligibility before planning on it. |

Tier 1 is needed by every workflow. Tier 2 adds depth to analysis and to own-telescope work.
Tier 3 is wavelength expansion, which needs domain tooling (CIAO, SAS, CASA) and should come after
the image engine is trustworthy.

**Important distinctions:**
- **SIMBAD** is an *object* database: identifiers, object types, basic data, selected measurements,
  and a curated **bibliography per object**. It is not a repository of catalogues.
- **VizieR** hosts the *published catalogues and tables* themselves (for example Gaia DR3 = `I/355`,
  2MASS PSC = `II/246`, AllWISE = `II/328`).
- **NED** is the extragalactic counterpart to SIMBAD, with redshifts and redshift-independent distances.

---

## 9. JWST and HST integration

### 9.1 JWST data products and processing stages

| Stage | Pipeline | Key products | Units / content | Platform use |
|-------|----------|--------------|-----------------|--------------|
| 0 (raw) | — | `_uncal` | DN, 4-D ramps `[nints, ngroups, ny, nx]` | Only for re-running Stage 1 (custom 1/f, jump, or saturation choices) |
| 1 | `calwebb_detector1` | `_rate`, `_rateints` | DN/s slope images, **no WCS** | Detector diagnostics, TSO pre-processing |
| 2 | `calwebb_image2` / `calwebb_spec2` | `_cal` (per exposure), `_s2d`, `_x1d` | MJy/sr (imaging), GWCS, flat-fielded, flux-calibrated | **Per-exposure photometry; input to custom Stage 3** |
| 3 | `calwebb_image3` / `spec3` / `coron3` / `ami3` / `tso3` | `_i2d` mosaic, `_cat.ecsv`, `_segm`, `_crf`, `_s3d` cubes, `_x1d`, `_whtlt` | Combined, outlier-rejected, Gaia-aligned (`tweakreg`) | **Default for exploration and "What am I looking at?"** |
| HLSP | community | e.g. PHANGS-JWST, CEERS, JADES mosaics and catalogues | Team-processed | Often the best science-ready products. Cite the HLSP. |

Rules:
- **Wrap the official `jwst` pipeline. Do not write a generic one.** Current release: `jwst` **3.0.0**
  (July 2026, DMS build B13.0, CRDS context 1581).
- Running locally needs `CRDS_PATH` and `CRDS_SERVER_URL`. The reference-file cache can be several GB.
- Record `CAL_VER` and `CRDS_CTX` from every file. MAST reprocesses data, so two downloads of
  "the same" product can differ.
- Instrument modes (via `EXP_TYPE`):

| Instrument | Imaging | Spectroscopy | Other | First-class support |
|------------|---------|--------------|-------|---------------------|
| **NIRCam** | SW 0.6–2.3 µm (0.031″/px), LW 2.4–5 µm (0.063″/px), simultaneous SW+LW | WFSS grisms | Coronagraphy, TSO | **Phase 1** imaging; WFSS later |
| **MIRI** | 5.6–25.5 µm (0.11″/px) | LRS (R≈100), MRS IFU 4.9–27.9 µm (R≈1500–3500) | Coronagraphy, TSO | Imaging in Phase 2; MRS cubes in Phase 4+ |
| **NIRSpec** | — (target acquisition only) | MOS (MSA), IFU (3″×3″), fixed slit, BOTS; prism R≈100, gratings R≈1000/2700 | TSO | Consume Stage-3 `x1d`/`s3d` in Phase 4+; no custom reduction early |
| **NIRISS** | Imaging (0.065″/px; `FILTER=CLEAR` + `PUPIL` = bandpass) | WFSS, SOSS | AMI | Imaging in Phase 1; SOSS only with the official pipeline |
| **FGS** | Guiding only | — | — | Not a science instrument for this platform; pointing metadata only |

Instrument knowledge to encode (`missions/jwst/`):
- pupil/filter pairing;
- detector to wavelength-channel mapping;
- PSF FWHM per filter, from STPSF or JDox tables (for example NIRCam F200W ≈ 0.064″, MIRI F2100W ≈ 0.67″);
- known artefacts: NIRCam wisps, claws, snowballs, 1/f striping; MIRI cruciform; persistence; saturation;
- photometric conversion (`PIXAR_SR`, aperture corrections from APCORR reference files).

### 9.2 HST

| Instrument (status) | Products | Calibration software | Platform notes |
|---------------------|----------|----------------------|----------------|
| **WFC3** UVIS/IR (active) | `raw` → `flt` (UVIS: `flc` = CTE-corrected) → `drz`/`drc` | `calwf3`, `drizzlepac` (AstroDrizzle, TweakReg) | e⁻/s. Photometry via `PHOTFLAM`/`PHOTPLAM` (and `PHOTFNU` for IR). Time-dependent zero points. |
| **ACS** WFC/SBC (active; HRC retired) | `flt`/`flc`/`drc` | `calacs`, `acstools` | CTE correction is essential for faint sources in recent data |
| **STIS** (active) | `x1d`, `x2d`, `crj` | `calstis` | Spectroscopy and coronagraphy |
| **COS** (active) | `x1d`/`x1dsum` | `calcos` | UV spectroscopy |
| WFPC2, NICMOS (legacy) | HLA products | — | Use the **Hubble Legacy Archive** and **Hubble Advanced Products** (single-visit and multi-visit mosaics) |
| Catalogues | **Hubble Source Catalog (HSC v3)** | — | Cross-match reference for HST-depth sources |

HST and JWST differ in ways the reader must handle:
- **units:** count rate vs surface brightness;
- **WCS:** HST uses FITS SIP and `WCSNAME` alternate solutions;
- **detector layout:** HST is multi-chip per file, with `EXTVER`.

The `missions/hst` and `missions/jwst` readers normalise both to `ImageProduct` with correct units
**without** losing the native header.

### 9.3 What "strong JWST/HST support" means, concretely (Phase 1–2 acceptance criteria)

1. Given a target name, list JWST/HST observations with program, PI, instrument, mode, **resolved
   bandpass**, exposure time, calibration level, data rights and date. Results are identical to the
   MAST Portal for the same query.
2. Download Stage-3 products with checksums and provenance.
3. Open `i2d`/`drz` with correct units, ERR, DQ mask and WCS. Plot with RA/Dec axes.
4. Aperture photometry of point sources agrees with the pipeline `_cat.ecsv` (JWST) or the HSC (HST)
   within the stated uncertainties, on a validation set.
5. Astrometric residuals vs Gaia DR3 (epoch-propagated) are reported per image.
6. Unsupported modes are **refused with an explanation**, never processed.

---

## 10. Multi-mission integration

| Mission | Python access | Native analysis tools | First supported use | Not before |
|---------|---------------|----------------------|---------------------|-----------|
| Gaia | `astroquery.gaia` (TAP, ADQL), GaiaXPy for XP spectra | — | Astrometric reference, PM/parallax, **XP synthetic photometry for calibrating own data** | — |
| TESS / Kepler / K2 | `lightkurve`, `astroquery.mast` | — | Light curves, transit ephemerides | — |
| Pan-STARRS | `astroquery.mast.Catalogs` (PS1 DR2), PS1 image cutout service | — | Photometric reference (δ ≥ −30°) | — |
| SDSS | `astroquery.sdss`, SkyServer/SciServer SQL | — | Spectra and redshifts for galaxies and QSOs in field | — |
| Chandra | `astroquery.heasarc`, CXC archive; CSC 2.1 via TAP | **CIAO** (separate conda environment) | Catalogue cross-match (X-ray counterparts), quick-look images | Spectral fitting (Phase 6+) |
| XMM-Newton | `astroquery.esa.xmm_newton`; 4XMM | **SAS** | Same as Chandra | Same |
| ALMA | `astroquery.alma` (TAP + DataLink) | **CASA** (for re-imaging) | Archive images and cubes, beam-aware comparison | Re-imaging visibilities |
| Euclid | ESA Euclid archive (TAP), astroquery ESA module | — | Q1 now; DR1-Foundation from Nov 2026: VIS/NISP imaging and catalogues | Weak-lensing products (mid-2027) |
| Rubin | Alert brokers (REST/Kafka); RSP if you have data rights | — | Bright-alert filtering for own follow-up (most alerts are too faint for amateur follow-up; filter to mag < 17) | Pixel data without data rights |

**Integration rule:** a mission is "supported" only when it has:
- an adapter;
- a reader that produces correct units, uncertainty and WCS;
- at least one **science validation test** against published values;
- documented caveats.

Until then it is "discoverable" (listed in searches, links shown) but not analysed.

---

## 14. Scientific-analysis engine

### 14.1 Structure

```
ImageProduct ─► quality checks ─► background ─► detection (matched filter, FP-controlled)
     │                                               │
     │                                               ▼
     │                                    measurements (aperture/PSF photometry with errors,
     │                                    shapes, sizes vs PSF, colours if multi-band)
     │                                               │
     ├──────► astrometric check vs Gaia ◄────────────┤
     │                                               ▼
     │                                    cross-match (§14.4) ─► known identities
     ▼                                               │
  metadata facts (§14.2)                             ▼
     └─────────────────────────────────► evidence engine (§14.3) ─► L1/L2/L3 statements
                                                     │
                                                     ▼
                                     assistant renders + literature links (Part 5)
```

Every node is a provenance-recorded step. Every measurement carries an uncertainty and a quality flag.

### 14.2 "What am I looking at?": metadata stage (Level 1 facts only)

| Fact | Source | If missing |
|------|--------|-----------|
| Telescope, instrument, detector | `TELESCOP`, `INSTRUME`, `DETECTOR` | State "unknown". Never infer from appearance. |
| Mode | `EXP_TYPE` / `OBSMODE` / own log | Refuse mode-dependent analysis |
| Bandpass (name, pivot λ, width) | Bandpass resolver | "Unknown bandpass" blocks physical interpretation |
| Exposure | `EFFEXPTM`/`EXPTIME`, number of combined exposures | — |
| Date / time scale | `DATE-OBS`, `MJD-AVG`, `TIMESYS` | — |
| Target as *requested* | `TARGNAME`, `TARG_RA/DEC`, program/PI | Reported as "the observer's target designation". It is **not** an identification of what is in the image. |
| Footprint, pixel scale | WCS / `S_REGION` | Plate-solve. If that fails, no sky-based identification. |
| Units, product level | `BUNIT`, filename suffix / `CAL_VER` | Block photometry |
| Depth | Measured: background RMS → 5σ point-source limit | — |
| Resolution | PSF FWHM measured on stars vs expected | — |

**Images without metadata** (a PNG from a press release, a phone photo through an eyepiece):
1. Check for an embedded AVM WCS.
2. Attempt a blind plate solve (astrometry.net).
3. If neither works, the system says it cannot identify objects reliably, and offers only an
   explicitly labelled *visual description*. It does not identify objects.

### 14.3 Evidence engine: the L1/L2/L3 hierarchy, enforced in code

```python
@dataclass(frozen=True)
class Statement:
    text: str
    level: Literal["L1_OBSERVATION", "L2_INFERENCE", "L3_HYPOTHESIS"]
    evidence: list[EvidenceRef]      # measurement IDs, catalogue rows, bibcode+passage, doc URL@version
    uncertainty: str | None          # quantitative where possible
    caveats: list[str]
    test: str | None                 # for L3: what observation/analysis would confirm or refute it
```

Promotion rules (deterministic, unit-tested):
- **L1** requires a measurement or metadata entity. Example: "A source at RA, Dec with F200W =
  21.30 ± 0.04 AB, FWHM consistent with the PSF."
- **L2** requires L1 evidence **and** a cited rule or knowledge item linking it to a physical
  interpretation. Examples:
  - "Unresolved, Gaia parallax 5.1 ± 0.1 mas at 0.04″ separation → a foreground Milky Way star."
  - "Extended, catalogued in NED with spectroscopic z → a background galaxy at that z."
- **L3** is anything else that is plausible. It must state *what would test it*. Examples:
  - "Arc-like extended source tangential to the cluster centre → candidate lensed arc; not in
    published lens catalogues; test: colour consistency of counter-images, spectroscopic redshift."
  - "Source absent in the reference epoch → candidate transient; first rule out an asteroid
    (SkyBoT), an artefact (DQ, persistence, wisps), and depth differences."
- The renderer may **downgrade** a statement but never upgrade it. The LLM receives statements, not
  raw freedom. A post-generation verifier checks that every rendered sentence maps to a statement ID
  with an equal or weaker level.

Structure classes and the minimum L1 evidence for an L2 interpretation:

| Structure | Minimum L1 evidence for L2 |
|-----------|----------------------------|
| Star | Point-like (size consistent with PSF) **and** (Gaia match with significant parallax/PM, **or** stellar colours plus a JWST/HST diffraction-spike pattern) |
| Galaxy | Resolved **and** (catalogue match with redshift or galaxy classification, **or** morphology plus colours inconsistent with a star) |
| Galaxy cluster | Catalogued cluster (NED/SIMBAD/VizieR cluster catalogues) at the field position, or a spectroscopic or red-sequence overdensity |
| Nebula / H II / PDR | Extended emission in a bandpass containing known diagnostic lines or PAH bands (e.g. F187N Paα, F212N H₂, F335M/F770W PAH) **and** a catalogued nebula or star-forming region |
| Dust structures | Extinction lanes in short-λ bands plus emission at long λ (MIRI); catalogued dark cloud |
| Supernova remnant | Catalogued SNR (e.g. Green's catalogue) plus morphology; otherwise L3 |
| Jets / outflows (HH objects) | Knotty, collimated emission in H₂/[Fe II] bands **and** a catalogued YSO/HH object; otherwise L3 |
| Gravitational lens | Published lens model or catalogue; otherwise L3 |
| Transient | Difference-image detection with S/N > 5, artefact and asteroid checks passed, and TNS/alert-broker match. A new discovery stays L3 until independent confirmation. |

### 14.4 Object identification and cross-matching

1. **Detect and measure:** positions with uncertainties σ_img (centroid error ≈ FWHM / (2.35 · S/N),
   plus the astrometric solution residual).
2. **Epoch propagation:** move Gaia DR3 (J2016.0) positions to the observation epoch using proper
   motions (`SkyCoord.apply_space_motion`). This matters at 0.03″/px for any star with PM above ~10 mas/yr.
3. **Match radius from errors, not a fixed arcsec:** r = k·√(σ_img² + σ_cat² + σ_pm²), with k ≈ 3–5,
   and both the radius and k reported.
4. **Chance coincidence:** P_chance = 1 − exp(−π r² ρ), where ρ is the local surface density of the
   catalogue (measured in an annulus). If P_chance > 1%, the match is flagged as ambiguous.
5. **Different resolutions or wavelengths** (e.g. X-ray or WISE positions against JWST): use a likelihood-ratio
   (Sutherland & Saunders 1992) or Bayesian cross-match (Budavári & Szalay 2008; NWAY, Salvato et
   al. 2018) rather than nearest neighbour.
6. **Sources** (queried in this order for identity):
   - SIMBAD (object type, identifiers, bibliography; check its coordinate-quality flag);
   - NED (extragalactic);
   - Gaia DR3;
   - VizieR catalogues by object class;
   - MAST (HSC, PS1);
   - SkyBoT (asteroids and comets in the field at the exposure mid-time);
   - TNS (transients).
7. **Report per source:**

| Column | Meaning |
|--------|---------|
| `src_id`, `ra`, `dec`, `pos_err` | Our measurement |
| `cat`, `cat_id`, `cat_epoch` | Catalogue, record identifier (as retrieved), epoch |
| `sep`, `sep_sigma`, `radius_used` | Separation in arcsec and in σ units |
| `p_chance`, `n_within_radius` | Ambiguity indicators |
| `identity_candidate`, `otype` | **Copied from the retrieved record**; never generated |
| `evidence_level` | L1 (positional coincidence) → L2 (consistent properties: magnitude, colour, PM) |
| `conflicts` | Disagreeing identifications (e.g. SIMBAD says star, NED says galaxy) are shown side by side, never silently resolved |
| `bibcodes` | From SIMBAD/NED records |

**No match** is reported as: "No catalogued counterpart within r (searched: SIMBAD, NED, Gaia DR3,
VizieR <list>)". It is never filled with a plausible-sounding name.

### 14.5 Combining personal observations with professional data (Part XVII)

The **comparison engine** answers "What do professional observatories know about this object?" and
"Compare my M51 image with HST and JWST":

1. **Discovery:** resolve the object, then use MOC/ObsCore across MAST, ESA, IRSA, ALMA, HEASARC.
   Group the results by wavelength regime, resolution and depth.
2. **Retrieval:** Stage-3/HLSP products only, with cutouts where available.
3. **Physical comparison table** (computed, not narrated):

| Quantity | Your image | HST (e.g. ACS F555W) | JWST (e.g. NIRCam F200W) |
|----------|-----------|-----------------------|--------------------------|
| Bandpass | from your filter definition | resolver | resolver |
| Resolution (FWHM) | measured from your stars (seeing-limited) | from header/PSF model | from STPSF/measured |
| Pixel scale | your plate solution | WCS | WCS |
| 5σ point-source depth | measured | measured | measured |
| What dominates the light | — | evolved stars plus ionised gas (with Hα/F658N) | old stellar populations; hot dust and PAH in MIRI |

4. **Spatial comparison:**
   - Reproject the professional data onto your grid.
   - Convolve it to your PSF (`create_matching_kernel`) to show what your telescope *would* see.
   - Also show the reverse: what is lost at your resolution.
5. **Photometric cross-calibration of your data:** Gaia DR3 XP spectra give synthetic photometry in
   Johnson-Cousins and SDSS systems (GaiaXPy, Gaia Synthetic Photometry Catalogue). This lets you
   calibrate your zero points with known colour terms, without a dedicated standard-star night. It is
   a major enabler for amateur photometry.
6. **Interpretation** with explicit limits:
   - "Your image can reproduce the large-scale spiral structure and the integrated colour gradient."
   - "It cannot resolve individual star clusters (HST resolves clusters at ~0.1″ ≈ a few pc at M51's distance)."
   - "It cannot see PAH emission (MIRI-only band)."
   - Every distance and scale value comes from a cited source.
