"""Reproduce the NGC 3132 example of the 2026-10-06 update report from public JWST data.

Steps:

1. Fetch row cutouts of three NIRCam long-wavelength Stage-3 mosaics of NGC 3132 (JWST
   program 2733) from MAST's public AWS copy. Only rows 480-1880 are transferred, about 53 MB
   in total; files already in the cache are reused.
2. Fetch the pipeline source catalogue of the F405N mosaic.
3. Build a chromatically ordered colour composite (R F470N, G F405N, B F356W).
4. Run aperture photometry at the pipeline's centroids and compare with the catalogue.
5. Run source detection and count false positives on the negated image.

Every step is recorded in a provenance database next to the outputs.

Usage::

    python examples/ngc3132_example.py --cache data/ngc3132 [--budget-mb 60]

Needs network access to ``stpubdata.s3.amazonaws.com`` and the ``imaging`` and ``archives``
extras (``pip install -e ".[imaging,archives]"``).
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from astropy.table import QTable

from astroledger.archives.cloud import DownloadLedger, fetch, fetch_rows, jwst_key
from astroledger.imaging import detect
from astroledger.io import open_image
from astroledger.photometry import aperture_photometry_table
from astroledger.provenance import ProvenanceStore, use_store
from astroledger.viz import make_rgb, show_rgb

ROWS = (480, 1880)
MOSAICS = {
    "jw02733-o001_t001_nircam_clear-f356w_i2d.fits": ("SCI",),
    "jw02733-o001_t001_nircam_f405n-f444w_i2d.fits": ("SCI", "ERR"),
    "jw02733-o001_t001_nircam_f444w-f470n_i2d.fits": ("SCI",),
}
CATALOG = "jw02733-o001_t001_nircam_f405n-f444w_cat.ecsv"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cache", type=Path, default=Path("data/ngc3132"))
    parser.add_argument("--budget-mb", type=float, default=60.0)
    args = parser.parse_args()
    cache = args.cache
    cache.mkdir(parents=True, exist_ok=True)
    ledger = DownloadLedger(budget_bytes=int(args.budget_mb * 1e6), log_path=cache / "ledger.tsv")

    with use_store(ProvenanceStore(cache / "provenance.sqlite")):
        images = []
        for name, extensions in MOSAICS.items():
            local = cache / f"{name.removesuffix('.fits')}_rows{ROWS[0]}-{ROWS[1]}.fits"
            if not local.exists():
                local = fetch_rows(
                    jwst_key(name), ROWS, cache, extensions=extensions, ledger=ledger
                )
            images.append(open_image(local))
        catalog_path = cache / CATALOG
        if not catalog_path.exists():
            catalog_path = fetch(jwst_key(CATALOG), cache, ledger=ledger)
        print(f"downloaded this run: {ledger.used_bytes / 1e6:.1f} MB")

        composite = make_rgb(images, percentile=99.8, stretch="asinh", a=0.03)
        figure = show_rgb(composite, title="NGC 3132 · JWST NIRCam (program 2733)")
        figure.savefig(cache / "ngc3132_rgb.png", dpi=150, bbox_inches="tight")
        print("composite:", ", ".join(f"{c['colour']}={c['bandpass']}" for c in composite.channels))

        f405n = images[1]
        catalog = QTable.read(catalog_path)
        params = catalog.meta["aperture_params"]
        y0 = f405n.header["CUTY0"]
        inside = (catalog["ycentroid"] > y0 + 20) & (
            catalog["ycentroid"] < y0 + ROWS[1] - ROWS[0] - 20
        )
        rows = catalog[inside]
        xy = np.column_stack([rows["xcentroid"], rows["ycentroid"] - y0])
        table = aperture_photometry_table(
            f405n,
            xy,
            float(params["aperture_radii"][1]),
            annulus=(params["bkg_aperture_inner_radius"], params["bkg_aperture_outer_radius"]),
        )
        ok = (
            np.isfinite(rows["aper50_flux"])
            & np.isfinite(table["flux"])
            & (table["masked_fraction"] == 0)
        )
        ratio = table["flux"][ok].to_value("Jy") / rows["aper50_flux"][ok].to_value("Jy")
        worst = np.max(np.abs(ratio - 1))
        print(f"photometry vs pipeline aper50 ({ok.sum()} sources): max |ratio - 1| = {worst:.1e}")

        detections = detect(f405n)
        print(
            f"detection: {len(detections.catalog)} sources, "
            f"{int(detections.catalog['near_bright_source'].sum())} flagged near a bright source, "
            f"{detections.n_false_estimate} negative-image detections"
        )


if __name__ == "__main__":
    main()
