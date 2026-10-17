"""Run the evidence engine on four NGC 3132 images and check its guarantees (task 18).

For each image (NIRCam F405N, F470N and F356W mosaic cutouts, and one MIRI F770W exposure) this
writes ``<image>_explain.json`` (every statement with its level and evidence) and
``<image>_explain.txt`` (readable report). It then verifies, and fails loudly otherwise:

1. **No fabricated identities.** Every ``Gaia DR3 <id>`` in any statement is a ``source_id``
   in the input Gaia table, and no catalogue-style name appears outside the statement that quotes
   the observer's target designation from the header.
2. **Every L2 has evidence.** Each L2 statement cites a measurement, a rule, and a catalogue
   record present in the input.

Usage::

    python examples/ngc3132_explain.py --cache data/ngc3132

Run ``ngc3132_example.py`` and ``ngc3132_astrometry.py`` first (they fetch the images and the
Gaia table into the same cache).
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from astropy.table import QTable

from astroledger.interpret import Level, explain, format_explanation
from astroledger.io import open_image
from astroledger.provenance import ProvenanceStore, last_activity, use_store, write_sidecar

IMAGES = (
    "jw02733-o001_t001_nircam_f405n-f444w_i2d_rows480-1880.fits",
    "jw02733-o001_t001_nircam_f444w-f470n_i2d_rows480-1880.fits",
    "jw02733-o001_t001_nircam_clear-f356w_i2d_rows480-1880.fits",
    "jw02733002001_02101_00001_mirimage_cal.fits",
)
CATALOGUE_NAME = re.compile(r"\b(NGC|IC|HD|HIP|2MASS|SDSS|PN)\s?\d|\bM\s?\d{1,3}\b")


def check(result, gaia) -> dict:
    """Verify the two guarantees; return the counts behind them."""
    known = {str(int(i)) for i in gaia["source_id"]}
    records = {f"Gaia DR3 {i}" for i in known}
    n_ids = 0
    for statement in result.statements():
        for found in re.findall(r"Gaia DR3 (\d+)", statement.text):
            n_ids += 1
            if found not in known:
                raise AssertionError(f"{statement.id}: Gaia DR3 {found} is not in the input")
        if statement.id != "IMG-2" and CATALOGUE_NAME.search(statement.text):
            raise AssertionError(f"{statement.id}: catalogue-style name in {statement.text!r}")
    l2 = [s for s in result.statements() if s.level is Level.L2_INFERENCE]
    for s in l2:
        kinds = {e.kind for e in s.evidence}
        cited = {e.ref for e in s.evidence if e.kind == "catalogue_record"}
        if not ({"measurement", "rule", "catalogue_record"} <= kinds and cited <= records):
            raise AssertionError(f"{s.id}: L2 without complete evidence")
    return {"identifiers_checked": n_ids, "l2_checked": len(l2)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cache", type=Path, default=Path("data/ngc3132"))
    args = parser.parse_args()
    out = args.cache / "explain"
    out.mkdir(exist_ok=True)
    gaia = QTable.read(args.cache / "gaia_dr3_ngc3132_cone.ecsv")
    summary = []
    with use_store(ProvenanceStore(args.cache / "provenance.sqlite")):
        for name in IMAGES:
            image = open_image(args.cache / name)
            result = explain(image, gaia=gaia)
            activity = last_activity()
            stem = name.removesuffix(".fits")
            path = out / f"{stem}_explain.json"
            path.write_text(json.dumps(result.to_dict(), indent=1, default=str))
            write_sidecar(path, activity)
            (out / f"{stem}_explain.txt").write_text(format_explanation(result, limit=15) + "\n")
            checked = check(result, gaia)
            row = {k: v for k, v in result.summary.items() if k != "psf_concentration"}
            row.update(checked)
            summary.append(row)
            print(json.dumps(row, default=str))
    (out / "explain_summary.json").write_text(json.dumps(summary, indent=1, default=str))
    print("all checks passed: no fabricated identities; every L2 has evidence")


if __name__ == "__main__":
    main()
