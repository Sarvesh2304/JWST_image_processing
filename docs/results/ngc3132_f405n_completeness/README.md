# NGC 3132 F405N point-source completeness (roadmap task 13)

Injection–recovery test on authentic JWST data. The input is rows 480–1880 of the Stage-3
mosaic `jw02733-o001_t001_nircam_f405n-f444w_i2d.fits` (program 2733, NIRCam F444W+F405N,
so the bandpass is F405N), from MAST's public AWS copy.

| File | Content |
|------|---------|
| `ngc3132_f405n_completeness.png` | Completeness vs injected AB magnitude for clean sky (> 65″ from the central star) and the nebula (< 50″); shaded bands are 68% Wilson intervals; ticks mark the 50% and 90% limits |
| `*_clean.ecsv`, `*_nebula.ecsv` | Per-level table (injected, recovered, completeness, interval, median flux ratio), with all settings and limits in the metadata |
| `*.prov.json` | Provenance: input file SHA-256, parameters, package versions, git commit; the figure's sidecar links the two runs |

Results (L1, measured by this test; 40 sources per level, seed 7, 22-star empirical PSF):

| Region | 50% complete | 90% complete |
|--------|--------------|--------------|
| Clean sky | AB 24.76 [24.72, 24.80] | AB 24.33 [24.20, 24.49] |
| Nebula | AB 23.44 [23.27, 24.62] | AB 21.12 [20.87, 21.36] |

Bracketed ranges are where the 68% Wilson bounds cross the level.

Interpretation (L2, from the measurement plus the detector's design):
- Inside the nebula, Brackett-α structure on scales below the 64 px background mesh raises the
  background RMS, and hence the detection threshold, to 1–3.5 MJy/sr. An AB 22 point source
  (peak about 6.8 MJy/sr) is therefore missed over part of the shell.
- The nebula's curve is flat between AB 22 and 24, so its 50% limit is poorly defined. Its
  wide range says so.
- A few bright injections on clean sky are lost because they merge with a neighbouring extended
  source (deblending is off by default). A real source there would be lost the same way.

Limitations:
- The PSF stamp is 25 px, so the far wings (about 10% of the light) are not injected.
- Errors on resampled mosaics are correlated.

Reproduce with `python examples/ngc3132_completeness.py --cache data/ngc3132` (downloads about
26 MB unless the cutout is already cached).
