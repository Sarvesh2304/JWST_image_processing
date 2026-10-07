# Legacy prototype (frozen)

These are the original scripts of this repository (commit `cccbb2c`), kept **unchanged** for comparison
and as a record of where the project started. They are **frozen**: `MANIFEST.sha256` records their
checksums, and the test suite fails if any of them changes.

> **Do not use their output scientifically, and do not build on them.**
> The audit in [`docs/lab-roadmap/01-repository-audit.md`](../docs/lab-roadmap/01-repository-audit.md)
> found, and [`docs/lab-roadmap/audit_checks.py`](../docs/lab-roadmap/audit_checks.py) reproduces:
> - `jwst_image_processor.py` / `jwst_main.py` cannot open JWST files (they read the empty primary HDU instead of `SCI`).
> - "Calibration" clips negative pixels to zero. On pure noise, this yields ~600 false "sources" in a 1024² image.
> - Bandpasses are taken from `FILTER` only, which mislabels NIRISS (`CLEAR` + `PUPIL`) and NIRCam pupil-wheel filters. Results keyed by that label overwrite each other.
> - `jwst_data_downloader.py` cannot work: wrong MAST endpoint, `ra=0, dec=0`, unsupported parameters.
> - Four of the six plotting functions in `jwst_visualizer.py` crash with current matplotlib.
> - `find_jwst_data.py` downloads the first row of an unfiltered query over the whole JWST collection, preferring uncalibrated `RATE` files.
>
> The replacement is a new package (`src/astroledger/`, working name), built step by step following `docs/lab-roadmap/`.

## The two changes made before freezing

`jwst_real_data_demo.py` used to save two archive files under **fabricated names**:
- `jw02756001001_02101_0000{1,2}_nrca1_rate.fits` was saved as `NGC_3132_F444W.fits` and `NGC_3132_F277W.fits`.
- Program 2756 is DDT imaging of Abell 2744, not NGC 3132 (NGC 3132 is ERO program 2733, observed without F444W).
- NRCA1 is a short-wavelength detector that cannot record F444W or F277W.

The script now keeps the archive filenames and describes the files truthfully.

`requirements.txt` gained `astroquery>=0.4.7`. `find_jwst_data.py` imports it, but it was missing.

All other files are byte-identical to `cccbb2c`, apart from moving into this directory.

## Corrections to claims in the original README
- **"Program 01063 (JWST Early Release Science)":** 1063 is not one of the ERS programs (their IDs are 1288–1386). Its actual category was not verified.
- **"Filter: CLEAR (broadband near-infrared)":** for NIRISS imaging, `FILTER=CLEAR` means the bandpass is set by the `PUPIL` element (F090W…F200W), which the scripts never read.
- **"Successfully processed REAL JWST data":** the files processed were Stage-1 `rate` files (DN/s, no flat field, no flux calibration, no WCS).
- **The sample image** `jwst_data/visualizations/sample_jwst_processing.png` is **synthetic**: a simulated spiral, and its "RGB composite" is the same image shifted by 10 and 20 pixels. It is not JWST data.
- **"Publication-quality", NIRSpec/MIRI support, "complete pipeline":** not met; see the audit's capability matrix.

## Running them (for comparison only)
From the repository root, with the legacy dependencies installed (`pip install -r legacy/requirements.txt`):

```bash
python legacy/jwst_demo.py          # synthetic demo; writes to ./jwst_data/visualizations/
python legacy/find_jwst_data.py     # needs network access to mast.stsci.edu
```

Python puts the script's own directory on `sys.path`, so the scripts still import each other from here.
