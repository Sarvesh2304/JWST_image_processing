# Evidence engine on four NGC 3132 images (roadmap task 18)

`astroledger explain` was run on four authentic JWST products of program 2733, with Gaia DR3
records for the field from MAST's HATS copy:
- three NIRCam mosaic cutouts: F405N, F470N and F356W, rows 480–1880;
- one MIRI F770W Stage-2 exposure.

[`examples/ngc3132_explain.py`](../../../examples/ngc3132_explain.py) produces these files and
checks the task's two criteria on every statement.

## Criteria: both pass on all four images

| Image | Sources | Gaia identifiers checked | L2 statements checked | Fabricated identities |
|-------|---------|--------------------------|-----------------------|-----------------------|
| NIRCam F405N | 551 | 49 | 18 | 0 |
| NIRCam F470N | 1,421 | 19 | 0 | 0 |
| NIRCam F356W | 1,577 | 18 | 0 | 0 |
| MIRI F770W | 233 | 21 | 7 | 0 |

- **Fabricated identities.** Every `Gaia DR3 <id>` quoted in a statement exists in the input Gaia
  table. No catalogue-style name appears anywhere except where the header's target designation
  is quoted, and that statement says it is a label, not an identification.
- **Evidence.** Every L2 statement cites a measurement, the rule it applies (R-STAR-PM) and the
  Gaia record.

## What the engine concluded

- **F405N:**
  - 150 sources are unresolved and 285 extended.
  - 25 coincide with Gaia DR3.
  - 18 are established as Milky Way stars (L2): unresolved, with Gaia proper motions significant
    at 8–38σ.
  - The other Gaia matches stay at L3 because their proper motion is not significant or missing.
- **MIRI F770W:** 7 stars are established at L2.
- **F470N and F356W:** no sizes are assessed and no star is established. These cutouts were
  downloaded without their ERR arrays (to save download budget), so measurement errors are
  unknown. The engine says so instead of classifying. The archive products do include ERR.
- **Galaxies and nebulae:** none are identified. Extended sources and line-band emission stay at
  L3, each with the test that would decide it. Identifying them needs NED or SIMBAD records, and
  the CDS hosts are blocked in this environment (task 16).

## What testing on real data changed

- **Size test.** Sizes from isophotal moments depend on S/N: faint sources looked 0.4–0.6 × the
  PSF. Resolved versus unresolved is now judged by light concentration, F(1.5 px)/F(4 px)
  compared with bright stars, with its error.
- **Spread floor.** A floor of 3% on the star-to-star spread of concentration stops pixel-phase
  effects from making point sources look extended.
- **No ERR, no size.** Without an error array, sizes are not classified and no PSF reference is
  reported.
- **Photometry.** `masked_fraction` in the aperture photometry is now clamped to [0, 1], so float
  noise no longer gives tiny negative values.

## Files

- `*_explain.txt`: readable reports. They show the first 15 sources, ordered by strongest
  statement.
- `explain_summary.json`: the counts above.
- `..._f405n-..._explain.json.gz`: every statement for F405N, gzip-compressed. Its `.prov.json`
  checksum refers to the uncompressed JSON.
