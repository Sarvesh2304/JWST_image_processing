# NGC 3132 astrometric quality against Gaia DR3 (roadmap task 14, project I1)

These are residuals of four authentic JWST products of program 2733 against Gaia DR3,
propagated with proper motion to each image's mid-exposure epoch (`MJD-AVG`).

**Inputs**
- Products from MAST's public AWS copy:
  - three NIRCam Stage-3 mosaics (rows 480–1880);
  - one MIRI Stage-2 exposure.
- 71 Gaia DR3 sources from MAST's HATS copy of Gaia DR3.

**Method**
- Sources come from `astroledger.imaging.detect`.
- Matching is one-to-one within 0.5″.
- Excluded:
  - Gaia two-parameter solutions;
  - stars near flagged pixels;
  - outliers beyond 3σ-equivalent (robust).

## Residuals per image (L1, measured)

Residuals are catalogue minus Gaia, in mas; ± values are 1σ.

| Image | Epoch | Matched / used | ΔRA·cos Dec | ΔDec | Robust σ (RA, Dec) | Rotation (″) | Post-fit RMS |
|-------|-------|----------------|-------------|------|--------------------|--------------|--------------|
| NIRCam F405N mosaic | 2022-06-03 | 31 / 19 | +20.4 ± 1.3 | +19.6 ± 1.3 | 4.6, 4.6 | 5.8 ± 3.3 | 4.8 |
| NIRCam F470N mosaic | 2022-06-03 | 26 / 14 | +15.1 ± 3.6 | −2.6 ± 3.6 | 10.8, 10.9 | 6.2 ± 14.2 | 18.2 |
| NIRCam F356W mosaic | 2022-06-03 | 23 / 10 | +9.4 ± 0.9 | +7.8 ± 2.7 | 2.4, 6.8 | 5.5 ± 8.6 | 8.5 |
| MIRI F770W exposure (Stage 2) | 2022-06-12 | 14 / 11 | −34.6 ± 5.4 | −35.0 ± 5.8 | 14.3, 15.4 | 75 ± 16 | 14.8 |

All products have `CAL_VER` 2.0.1. The NIRCam pixel scale is 63 mas, so the F405N offset is
(0.40, 0.20) pixel in the image frame.

## Checks

- **Our centroids are not the cause.** The JWST pipeline's own source catalogues give the same
  offsets from Gaia:
  - F405N: +21.1 ± 0.6, +19.5 ± 0.9 mas (33 stars);
  - F470N: +15.0 ± 2.2, −3.1 ± 2.9 mas (25 stars).

  The offsets are therefore properties of the products' WCS.
- **Epoch propagation is needed.** Against Gaia at J2016.0, without propagation, the F405N scatter
  grows from about 3 mas to 14–18 mas. `tests/science/test_astrometry_vs_gaia.py` keeps this in CI.

## Interpretation

- **L2 (from the measurements and the product type).**
  - Each Stage-3 mosaic agrees with Gaia DR3 to 10–30 mas.
  - The mosaics are offset from each other by up to about 20 mas. Matching sources between these
    filters therefore needs a tolerance of at least that size, or a re-registration.
  - The Stage-2 MIRI exposure has not been through Stage-3 alignment. It is offset by about 50 mas
    and rotated by about 75″.
- **L3 hypothesis.** The NIRCam offsets come from how each mosaic was aligned in Stage 3 (the
  reference catalogue and epoch used by `tweakreg`).

  *Test:* rerun Stage 3 with `tweakreg` set to align to Gaia DR3 at the observation epoch, or
  compare with a later reprocessing of the same products; the offsets should then shrink to the
  scatter level.

## Limitations

- These are 10–20 stars per image, across a 148″ × 88″ field. The rotation and scale fits are
  therefore weak except in F405N.
- F470N centroids are noisier, which is consistent with bright H₂ nebulosity around the stars.

## Files

- `astrometry_summary.ecsv`: one row per image.
- `*_gaia_matches.ecsv`: every match and its flags. The metadata holds the summary, the fit and
  the notes.
- `*_gaia_qa.png`: the QA figures.
- `*.prov.json`: provenance records.

Reproduce with `python examples/ngc3132_astrometry.py --cache data/ngc3132`.
