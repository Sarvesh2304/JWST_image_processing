# Authentic pixel fixtures

`jw02733-o001_t001_nircam_f405n-f444w_i2d_stamps.fits` holds three 33×33-pixel postage stamps
(`SCI`/`ERR` with `EXTVER` 1–3) of stars in the public JWST Stage-3 mosaic
`jw02733-o001_t001_nircam_f405n-f444w_i2d.fits`. That mosaic is from program 2733 (NGC 3132),
NIRCam F405N, pipeline 2.0.1.

How the stamps were made:
- the source rows were read from MAST's public AWS copy (`s3://stpubdata`) on 2026-10-06, with
  `astroledger.archives.cloud.fetch_rows`;
- pixel values are unchanged;
- headers are copied from the archive product, with `CRPIXn` shifted;
- `CUTX0`/`CUTY0` give each stamp's 0-based offset in the original mosaic.

`jw02733-o001_t001_nircam_f405n-f444w_cat_subset.ecsv` holds the JWST pipeline's own catalogue
rows for those stars (labels 102, 225, 122), from `jw02733-o001_t001_nircam_f405n-f444w_cat.ecsv`.
Its metadata keeps the pipeline's aperture radii, background annulus and aperture corrections.

`tests/science/test_photometry_vs_pipeline.py` uses them to check that astroledger reproduces the
pipeline's aperture photometry on authentic data.

## Astrometry fixtures (roadmap task 14)

`gaia_dr3_ngc3132_cone.ecsv` holds 71 Gaia DR3 sources within 88″ of NGC 3132. They were read on
2026-10-07 from MAST's HATS copy of Gaia DR3 on AWS
(`s3://stpubdata/gaia/gaia_dr3/public/hats/gaia/`, partition Norder=4/Npix=2407, row group 0) with
`astroledger.archives.gaia.gaia_cone`. The values are unchanged: positions at `ref_epoch` J2016.0,
proper motions, errors, G magnitude and `astrometric_params_solved`.

`jw02733-o001_t001_nircam_f405n-f444w_cat_gaia_subset.ecsv` holds the 44 rows of the JWST pipeline
catalogue `jw02733-o001_t001_nircam_f405n-f444w_cat.ecsv` (jwst 2.0.1) that lie within 1″ of a
Gaia source. Values are unchanged.

`tests/science/test_astrometry_vs_gaia.py` uses them, with the observation epoch read from the
stamps' authentic `MJD-AVG`.
