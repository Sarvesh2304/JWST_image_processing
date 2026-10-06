# Authentic FITS headers (no pixel data)

Primary (and one SCI) headers copied verbatim from public JWST products of program 2733
(NGC 3132, ERO), read from MAST's public AWS copy (`s3://stpubdata/jwst/public/jw02733/`)
on 2026-10-06. Each file is named after the archive product it came from, plus `.primary.txt` or `.sci.txt`.

They let tests check metadata handling (e.g. bandpass resolution) against real headers in CI,
without network access or large files. Load with `astropy.io.fits.Header.fromtextfile`.
