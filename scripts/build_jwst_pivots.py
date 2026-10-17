"""Build ``src/astroledger/core/data/jwst_pivots.ecsv`` from STScI's published throughput tables.

Source: the throughput tables shipped in STScI's ``mirage`` package (the official NIRCam/NIRISS
image simulator), wheel ``mirage-2.5.0-py3-none-any.whl`` from PyPI:

- NIRCam: ``mirage/config/<FILTER>_<PUPIL>_nircam_plus_ote_throughput_mod{a,b}_sorted.txt``
  (filter wheel, pupil wheel; filter + telescope throughput, per module);
- NIRISS: ``mirage/config/<filter>_niriss_throughput1.txt``.

Pivot wavelength (photon-counting convention):
``lambda_p**2 = integral(T * lambda dlambda) / integral(T / lambda dlambda)``,
integrated with the trapezoid rule on each table's own wavelength grid.

Weak lenses (WLP4, WLP8) are wavefront-sensing optics, not science bandpasses, and are skipped.
MIRI is not covered by mirage, so no MIRI pivots are produced.

Usage::

    pip download --no-deps mirage==2.5.0 -d /tmp/mirage
    python scripts/build_jwst_pivots.py /tmp/mirage/mirage-2.5.0-py3-none-any.whl
"""

from __future__ import annotations

import hashlib
import re
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from astropy.table import Table

OUT = Path(__file__).resolve().parents[1] / "src/astroledger/core/data/jwst_pivots.ecsv"
NIRCAM = re.compile(
    r"mirage/config/(\w+?)_(\w+?)_nircam_plus_ote_throughput_mod([ab])_sorted\.txt$"
)
NIRISS = re.compile(r"mirage/config/(f\w+)_niriss_throughput1\.txt$")


def _pivot(text: str) -> float:
    rows = [line.split() for line in text.splitlines() if line.strip()]
    values = np.array([r[:2] for r in rows if _number(r[0])], dtype=float)
    lam, thr = values[:, 0], values[:, 1]
    return float(np.sqrt(np.trapezoid(thr * lam, lam) / np.trapezoid(thr / lam, lam)))


def _number(token: str) -> bool:
    try:
        float(token)
    except ValueError:
        return False
    return True


def main(wheel: str) -> None:
    wheel_path = Path(wheel)
    digest = hashlib.sha256(wheel_path.read_bytes()).hexdigest()
    rows = []
    with zipfile.ZipFile(wheel_path) as archive:
        for name in sorted(archive.namelist()):
            if match := NIRCAM.match(name):
                filt, pupil, module = match.groups()
                if "WLP" in filt or "WLP" in pupil:
                    continue
                band = filt if pupil == "CLEAR" else pupil
                pivot = _pivot(archive.read(name).decode())
                rows.append(("NIRCAM", filt, pupil, band, module.upper(), pivot, name))
            elif match := NIRISS.match(name):
                band = match.group(1).upper()
                pivot = _pivot(archive.read(name).decode())
                rows.append(("NIRISS", "", "", band, "", pivot, name))
    table = Table(
        rows=rows,
        names=(
            "instrument",
            "filter_wheel",
            "pupil_wheel",
            "bandpass",
            "module",
            "pivot_um",
            "source_file",
        ),
    )
    table["pivot_um"].info.format = ".5f"
    table.meta = {
        "description": "JWST pivot wavelengths computed from STScI throughput tables",
        "source_package": "mirage 2.5.0 (STScI), PyPI wheel mirage-2.5.0-py3-none-any.whl",
        "source_sha256": digest,
        "definition": "lambda_p^2 = int(T lambda dlambda) / int(T / lambda dlambda)",
        "throughput": "NIRCam: filter + OTE per module; NIRISS: as tabulated",
        "generated_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generator": "scripts/build_jwst_pivots.py",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    table.write(OUT, format="ascii.ecsv", overwrite=True)
    print(f"{len(table)} rows -> {OUT}")


if __name__ == "__main__":
    main(sys.argv[1])
