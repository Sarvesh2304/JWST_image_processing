# Authentic FITS headers (no pixel data)

Primary (and one SCI) headers copied verbatim from public JWST products of program 2733
(NGC 3132, ERO), read from MAST's public AWS copy (`s3://stpubdata/jwst/public/jw02733/`)
on 2026-10-06. Each file is named after the archive product it came from, plus `.primary.txt` or `.sci.txt`.

They let tests check metadata handling (e.g. bandpass resolution) against real headers in CI,
without network access or large files. Load with `astropy.io.fits.Header.fromtextfile`.

## Mode-router headers (roadmap task 15)

These primary headers were read verbatim on 2026-10-07 from Stage-3 products of public JWST
programs in MAST's AWS copy (`s3://stpubdata/jwst/public/jwNNNNN/L3/t/...`), with
`astroledger.archives.cloud.remote_hdus` (headers only, no pixel data):

| File | `EXP_TYPE` | `TSOVISIT` |
|------|------------|------------|
| `jw02736-o003_t001_niriss_clear-f115w_i2d.fits.primary.txt` | NIS_IMAGE | F |
| `jw01386-c1020_t001_nircam_f444w-maskrnd-sub320a335r_i2d.fits.primary.txt` | NRC_CORON | F |
| `jw01386-c1021_t001_miri_f1140c-mask1140_i2d.fits.primary.txt` | MIR_4QPM | F |
| `jw01386-c1023_t001_niriss_f380m-nrm-sub80_aminorm-oi.fits.primary.txt` | NIS_AMI | F |
| `jw01386-o013_t004_nirspec_g140h-f100lp_s3d.fits.primary.txt` | NRS_IFU | F |
| `jw01366-o001_t001_niriss_clear-gr700xd-substrip256_x1dints.fits.primary.txt` | NIS_SOSS | T |
| `jw01366-o002_t001_nircam_f322w2-grismr-subgrism256_x1dints.fits.primary.txt` | NRC_TSGRISM | T |
| `jw01366-o004_t001_nirspec_clear-prism-s1600a1-sub512_x1dints.fits.primary.txt` | NRS_BRIGHTOBJ | T |
| `jw01366-o011_t002_miri_p750l-slitlessprism_x1dints.fits.primary.txt` | MIR_LRS-SLITLESS | T |

The coronagraphic `_i2d` files are 2-D images on disk. They show why the mode, not the array
shape, decides whether image analysis is valid.
