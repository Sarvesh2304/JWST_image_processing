"""Astrometric quality of NGC 3132 JWST images against Gaia DR3 (roadmap task 14, project I1).

For each image:

1. detect sources (:func:`astroledger.imaging.detect`);
2. propagate Gaia DR3 to the image's mid-exposure epoch and match within 0.5";
3. report the median offset, scatter and a shift/rotation/scale fit, excluding Gaia stars
   without proper motion and stars near flagged (e.g. saturated) pixels;
4. save the matches (ECSV), a figure and provenance sidecars.

A summary table with one row per image is written to ``astrometry_summary.ecsv``.

Inputs (all from MAST's public AWS copy; reused from the cache when present):

- row cutouts of the NIRCam F405N, F470N and F356W Stage-3 mosaics (as in
  ``ngc3132_example.py``);
- the MIRI F770W Stage-2 exposure ``jw02733002001_02101_00001_mirimage_cal.fits`` (29.7 MB);
- Gaia DR3 within 88" of the nebula (about 13.5 MB of Parquet reads).

Usage::

    python examples/ngc3132_astrometry.py --cache data/ngc3132 [--budget-mb 120]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.table import QTable

from astroledger.archives.cloud import DownloadLedger, fetch, fetch_rows, jwst_key
from astroledger.archives.gaia import gaia_cone
from astroledger.astrometry import astrometric_qa, plot_astrometric_qa
from astroledger.imaging import detect
from astroledger.io import open_image
from astroledger.provenance import (
    ProvenanceStore,
    last_activity,
    sha256_file,
    use_store,
    write_sidecar,
)

ROWS = (480, 1880)
MOSAICS = {
    "jw02733-o001_t001_nircam_f405n-f444w_i2d.fits": ("SCI", "ERR"),
    "jw02733-o001_t001_nircam_f444w-f470n_i2d.fits": ("SCI",),
    "jw02733-o001_t001_nircam_clear-f356w_i2d.fits": ("SCI",),
}
MIRI = "jw02733002001_02101_00001_mirimage_cal.fits"
#: Cone centre near NGC 3132's central star and radius covering the cutouts (ICRS).
CENTRE = SkyCoord(151.75749 * u.deg, -40.43651 * u.deg)
RADIUS = 88.32 * u.arcsec


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cache", type=Path, default=Path("data/ngc3132"))
    parser.add_argument("--budget-mb", type=float, default=120.0)
    args = parser.parse_args()
    cache = args.cache
    cache.mkdir(parents=True, exist_ok=True)
    ledger = DownloadLedger(budget_bytes=int(args.budget_mb * 1e6), log_path=cache / "ledger.tsv")
    out_dir = cache / "astrometry"
    out_dir.mkdir(exist_ok=True)

    with use_store(ProvenanceStore(cache / "provenance.sqlite")):
        gaia_path = cache / "gaia_dr3_ngc3132_cone.ecsv"
        if gaia_path.exists():
            gaia = QTable.read(gaia_path)
        else:
            gaia = gaia_cone(CENTRE, RADIUS, ledger=ledger)
            gaia.write(gaia_path, format="ascii.ecsv")
            write_sidecar(gaia_path, last_activity())

        paths = []
        for name, extensions in MOSAICS.items():
            local = cache / f"{name.removesuffix('.fits')}_rows{ROWS[0]}-{ROWS[1]}.fits"
            if not local.exists():
                local = fetch_rows(
                    jwst_key(name), ROWS, cache, extensions=extensions, ledger=ledger
                )
            paths.append(local)
        miri = cache / MIRI
        paths.append(miri if miri.exists() else fetch(jwst_key(MIRI), cache, ledger=ledger))

        rows = []
        for path in paths:
            image = open_image(path)
            product = "Stage-3 mosaic" if "_i2d" in path.name else "Stage-2 exposure"
            label = f"{image.bandpass.key} {product}"
            qa = astrometric_qa(detect(image).catalog, gaia, image=image)
            activity = last_activity()
            stem = path.name.removesuffix(".fits")
            matches = out_dir / f"{stem}_gaia_matches.ecsv"
            qa.matches.meta.update({"summary": qa.summary, "fit": qa.fit, "notes": qa.notes})
            qa.matches.write(matches, format="ascii.ecsv", overwrite=True)
            write_sidecar(matches, activity)
            figure = plot_astrometric_qa(
                qa, title=f"{label} vs Gaia DR3 at {qa.summary['epoch'][:10]}"
            )
            figure_path = out_dir / f"{stem}_gaia_qa.png"
            figure.savefig(figure_path, dpi=120, bbox_inches="tight")
            figure_path.with_name(figure_path.name + ".prov.json").write_text(
                json.dumps(
                    {
                        "output_file": {
                            "path": figure_path.name,
                            "sha256": sha256_file(figure_path),
                        },
                        "made_by": "astroledger.astrometry.plot_astrometric_qa",
                        "from_activity": activity.id,
                    },
                    indent=2,
                )
            )
            s, fit = qa.summary, qa.fit or {}
            rows.append(
                {
                    "file": path.name,
                    "bandpass": image.bandpass.key,
                    "cal_ver": image.primary_header.get("CAL_VER", "unknown"),
                    "epoch_utc": s["epoch"],
                    "n_matched": s["n_matched"],
                    "n_used": s["n_used"],
                    "median_dra_mas": s.get("median_dra_mas", np.nan),
                    "median_dra_err_mas": s.get("median_dra_err_mas", np.nan),
                    "median_ddec_mas": s.get("median_ddec_mas", np.nan),
                    "median_ddec_err_mas": s.get("median_ddec_err_mas", np.nan),
                    "robust_sigma_dra_mas": s.get("robust_sigma_dra_mas", np.nan),
                    "robust_sigma_ddec_mas": s.get("robust_sigma_ddec_mas", np.nan),
                    "rotation_arcsec": fit.get("rotation_arcsec", np.nan),
                    "rotation_err_arcsec": fit.get("rotation_err_arcsec", np.nan),
                    "scale_ppm": fit.get("scale_ppm", np.nan),
                    "scale_err_ppm": fit.get("scale_err_ppm", np.nan),
                    "rms_after_fit_mas": fit.get("rms_after_mas", np.nan),
                }
            )
            print(f"== {path.name}\n{qa.report()}\n")
        summary = QTable(rows=rows)
        summary.meta["description"] = (
            "Per-image astrometric residuals (catalogue minus Gaia DR3 at the image epoch), L1"
        )
        summary.write(out_dir / "astrometry_summary.ecsv", format="ascii.ecsv", overwrite=True)
        print(f"downloaded this run: {ledger.used_bytes / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
