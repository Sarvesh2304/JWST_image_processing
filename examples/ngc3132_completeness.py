"""Point-source completeness of the NGC 3132 F405N mosaic by injection-recovery (task 13).

Steps:

1. Fetch rows 480-1880 of the F405N Stage-3 mosaic (JWST program 2733, SCI and ERR, about
   26 MB) from MAST's public AWS copy, unless already in the cache.
2. Build an empirical PSF from bright, isolated, round stars found by the detector.
3. Inject 40 point sources per level (AB 18-27 in 0.5 mag steps) on clean sky (> 65" from the
   nebula's centre) and inside the nebula (< 50"), detect with the science settings, and count
   recoveries within 1.5 px.
4. Save one ECSV table per region (with provenance sidecars) and the completeness figure.

Usage::

    python examples/ngc3132_completeness.py --cache data/ngc3132

Needs the ``imaging`` and ``archives`` extras. Shares its cache with ``ngc3132_example.py``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from astropy.coordinates import SkyCoord
from astropy.wcs.utils import proj_plane_pixel_scales

from astroledger.archives.cloud import DownloadLedger, fetch_rows, jwst_key
from astroledger.imaging import detect, empirical_psf, injection_recovery, plot_completeness
from astroledger.io import open_image
from astroledger.provenance import (
    ProvenanceStore,
    last_activity,
    sha256_file,
    use_store,
    write_sidecar,
)

ROWS = (480, 1880)
MOSAIC = "jw02733-o001_t001_nircam_f405n-f444w_i2d.fits"
#: Approximate centre of NGC 3132's central star (ICRS); used only to define the two regions.
CENTRE = SkyCoord(151.757, -40.4365, unit="deg")
LEVELS = np.arange(18.0, 27.01, 0.5)


def psf_stars(image) -> np.ndarray:
    """Bright, isolated, round, unflagged detections away from the edges."""
    catalog = detect(image).catalog
    x, y = np.asarray(catalog["x"]), np.asarray(catalog["y"])
    nearest = np.array([np.sort(np.hypot(x - xi, y - yi))[1] for xi, yi in zip(x, y, strict=True)])
    ny, nx = image.data.shape
    good = (
        (x > 20)
        & (x < nx - 20)
        & (y > 20)
        & (y < ny - 20)
        & (catalog["snr"] > 100)
        & ~catalog["near_bright_source"]
        & (catalog["ellipticity"] < 0.15)
        & (nearest > 30)
    )
    return np.column_stack([x[good], y[good]])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cache", type=Path, default=Path("data/ngc3132"))
    parser.add_argument("--budget-mb", type=float, default=30.0)
    args = parser.parse_args()
    cache = args.cache
    cache.mkdir(parents=True, exist_ok=True)
    ledger = DownloadLedger(budget_bytes=int(args.budget_mb * 1e6), log_path=cache / "ledger.tsv")

    with use_store(ProvenanceStore(cache / "provenance.sqlite")):
        local = cache / f"{MOSAIC.removesuffix('.fits')}_rows{ROWS[0]}-{ROWS[1]}.fits"
        if not local.exists():
            local = fetch_rows(
                jwst_key(MOSAIC), ROWS, cache, extensions=("SCI", "ERR"), ledger=ledger
            )
        image = open_image(local)
        stars = psf_stars(image)
        psf = empirical_psf(image, stars)

        ny, nx = image.data.shape
        cx, cy = image.wcs.world_to_pixel(CENTRE)
        yy, xx = np.mgrid[:ny, :nx]
        scale = float(np.mean(proj_plane_pixel_scales(image.wcs.celestial))) * 3600.0  # arcsec
        radius = np.hypot(xx - cx, yy - cy) * scale
        regions = {
            'clean sky (>65")': ("clean", radius > 65),
            'nebula (<50")': ("nebula", radius < 50),
        }
        results, activities = [], {}
        for label, (tag, region) in regions.items():
            result = injection_recovery(
                image, LEVELS, psf=psf, n_per_level=40, region=region, seed=7
            )
            results.append(result)
            table_path = cache / f"ngc3132_f405n_completeness_{tag}.ecsv"
            result.table.write(table_path, format="ascii.ecsv", overwrite=True)
            write_sidecar(table_path, last_activity())
            activities[label] = {"activity_id": last_activity().id, "table": table_path.name}
            for key, value in result.limits.items():
                span = result.limit_ranges[key]
                print(f"{label}: {key} complete at AB {value} (68% range {span})")
            for note in result.notes:
                print("  note:", note)

        figure = plot_completeness(
            results,
            list(regions),
            title=(
                "NGC 3132, JWST NIRCam F405N: point-source completeness "
                f"({len(stars)}-star empirical PSF)"
            ),
        )
        out = cache / "ngc3132_f405n_completeness.png"
        figure.savefig(out, bbox_inches="tight")
        out.with_name(out.name + ".prov.json").write_text(
            json.dumps(
                {
                    "output_file": {"path": out.name, "sha256": sha256_file(out)},
                    "made_by": "astroledger.imaging.plot_completeness",
                    "from_activities": activities,
                },
                indent=2,
            )
        )
        print("figure:", out)


if __name__ == "__main__":
    main()
