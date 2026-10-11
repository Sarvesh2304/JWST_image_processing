"""Cross-match NGC 3132 F405N and F470N detections with the error-based engine (task 17).

Steps:

1. Detect sources in the NIRCam F405N and F470N mosaic cutouts (program 2733).
2. Positional errors:
   - F405N: per source, FWHM / (2.35 S/N);
   - F470N: the cutout has no ERR extension, so no S/N is available. A uniform 11 mas is used
     instead: the positional scatter of F470N detections against Gaia DR3 measured in task 14.
3. Cross-match the compact F405N sources (FWHM < 3.5 px, S/N > 20, not flagged as near a bright
   source) against all F470N detections, with registration (frame offset removed) and k = 4.
4. Save the best-match, candidate and conflict tables (ECSV, with provenance) and a figure.
   The figure compares the matched separations, in units of their errors, with the Rayleigh
   distribution expected if the error model is right.

Usage::

    python examples/ngc3132_crossmatch.py --cache data/ngc3132

Shares its cache with ``ngc3132_example.py`` (needs the F405N and F470N row cutouts).
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from astropy import units as u
from scipy.stats import kstest, rayleigh

from astroledger.archives.cloud import DownloadLedger, fetch_rows, jwst_key
from astroledger.crossmatch import centroid_error, crossmatch
from astroledger.imaging import detect
from astroledger.io import open_image
from astroledger.provenance import ProvenanceStore, last_activity, use_store, write_sidecar

ROWS = (480, 1880)
F405N = "jw02733-o001_t001_nircam_f405n-f444w_i2d.fits"
F470N = "jw02733-o001_t001_nircam_f444w-f470n_i2d.fits"
SIGMA_F470N = 11 * u.mas  # task 14: robust scatter of F470N detections against Gaia DR3


def _image(cache, name, extensions, ledger):
    local = cache / f"{name.removesuffix('.fits')}_rows{ROWS[0]}-{ROWS[1]}.fits"
    if not local.exists():
        local = fetch_rows(jwst_key(name), ROWS, cache, extensions=extensions, ledger=ledger)
    return open_image(local)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cache", type=Path, default=Path("data/ngc3132"))
    parser.add_argument("--budget-mb", type=float, default=45.0)
    args = parser.parse_args()
    cache = args.cache
    cache.mkdir(parents=True, exist_ok=True)
    out = cache / "crossmatch"
    out.mkdir(exist_ok=True)
    ledger = DownloadLedger(budget_bytes=int(args.budget_mb * 1e6), log_path=cache / "ledger.tsv")

    with use_store(ProvenanceStore(cache / "provenance.sqlite")):
        f405n = _image(cache, F405N, ("SCI", "ERR"), ledger)
        f470n = _image(cache, F470N, ("SCI",), ledger)
        a = detect(f405n).catalog
        b = detect(f470n).catalog
        scale = 0.06303 * u.arcsec / u.pix  # NIRCam long-wavelength mosaic pixel (CDELT)
        a["pos_err"] = centroid_error(u.Quantity(a["fwhm"]) * scale, a["snr"]).to(u.mas)
        compact = (
            (np.asarray(a["fwhm"]) < 3.5)
            & (np.asarray(a["snr"]) > 20)
            & ~np.asarray(a["near_bright_source"])
        )
        a = a[compact]
        result = crossmatch(
            a,
            b,
            sigma_a="pos_err",
            sigma_b=SIGMA_F470N,
            k=4.0,
            register=True,
            copy_columns=("label",),
        )
        activity = last_activity()
        for name, table in (
            ("best", result.best),
            ("candidates", result.candidates),
            ("conflicts", result.conflicts),
        ):
            table.meta.update({"crossmatch": result.meta, "notes": result.notes})
            path = out / f"f405n_compact_x_f470n_{name}.ecsv"
            table.write(path, format="ascii.ecsv", overwrite=True)
            write_sidecar(path, activity)

        matched = np.asarray(result.best["b_index"]) >= 0
        ratio = np.sort(np.asarray(result.best["sep_sigma"])[matched])
        reg = result.meta["registration"]
        print(f"F405N compact sources: {len(a)}; F470N detections: {len(b)}")
        print(
            f"registration: offset ({reg['offset_dra_arcsec'] * 1e3:.1f}, "
            f"{reg['offset_ddec_arcsec'] * 1e3:.1f}) +- {reg['offset_err_arcsec'] * 1e3:.1f} mas "
            f"from {reg['n_pairs']} pairs; "
            f"sigma_sys {result.meta['sigma_sys_arcsec'] * 1e3:.1f} mas"
        )
        ks = kstest(ratio, rayleigh.cdf)  # separation/sigma ~ Rayleigh(1) if errors are right
        print(f"KS test against Rayleigh: D = {ks.statistic:.3f}, p = {ks.pvalue:.2f}")
        print(
            f"matched {matched.sum()}; within 2 sigma {np.mean(ratio <= 2):.2f} (Rayleigh 0.86); "
            f"conflicts {result.meta['n_conflicts']}; prior Q {result.meta['prior_q']:.2f}"
        )

        fig, ax = plt.subplots(figsize=(5.6, 3.8), dpi=150)
        fig.patch.set_facecolor("#fcfcfb")
        ax.set_facecolor("#fcfcfb")
        grid = np.linspace(0, 4.2, 200)
        ax.plot(
            grid,
            1 - np.exp(-(grid**2) / 2),
            color="#9a9994",
            lw=1.5,
            label="Rayleigh (error model)",
        )
        ax.step(
            ratio,
            np.arange(1, len(ratio) + 1) / len(ratio),
            where="post",
            color="#2a78d6",
            lw=2,
            label=f"matched pairs (n = {len(ratio)})",
        )
        ax.set_xlabel("separation / combined error", color="#0b0b0b")
        ax.set_ylabel("cumulative fraction", color="#0b0b0b")
        ax.set_xlim(0, 4.2)
        ax.set_ylim(0, 1.02)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        ax.tick_params(colors="#52514e", labelsize=8)
        ax.legend(frameon=False, fontsize=8, loc="lower right")
        ax.set_title(
            "NGC 3132: F405N compact sources vs F470N, after registration",
            fontsize=9,
            loc="left",
            color="#0b0b0b",
        )
        figure = out / "f405n_compact_x_f470n_separations.png"
        fig.savefig(figure, bbox_inches="tight")
        print("figure:", figure)


if __name__ == "__main__":
    main()
