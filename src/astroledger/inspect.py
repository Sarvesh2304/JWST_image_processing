"""Level-1 fact sheet for an image: what the file states and what its pixels measure.

Everything reported is either read from the file (metadata) or measured from unmasked pixels.
Nothing is inferred about the objects in the image. The target keyword is reported as the
observer's designation, which is not an identification of what the image contains.
"""

from __future__ import annotations

import re
from typing import Any

import numpy as np
from astropy.stats import sigma_clipped_stats
from astropy.wcs.utils import proj_plane_pixel_scales

from astroledger.core.product import ImageProduct

__all__ = ["fact_sheet", "format_fact_sheet", "product_level"]

_ROUTINE_FIX = re.compile(r"FITSFixedWarning: '(datfix|obsfix)'")

_JWST_LEVELS = {
    "uncal": "Stage 0: uncalibrated ramps",
    "rate": "Stage 1: count-rate image (DN/s, no flux calibration or WCS)",
    "rateints": "Stage 1: per-integration count rates",
    "cal": "Stage 2: calibrated exposure",
    "crf": "Stage 3 input: calibrated exposure with outliers flagged",
    "i2d": "resampled image",
}
_HST_LEVELS = {
    "raw": "raw exposure",
    "flt": "calibrated exposure",
    "flc": "calibrated exposure, CTE-corrected",
    "drz": "drizzled combined image",
    "drc": "drizzled combined image, CTE-corrected",
}


def product_level(filename: str, telescope: str | None) -> str:
    """Processing level inferred from the archive filename suffix (stated as such)."""
    stem = filename.removesuffix(".fits").removesuffix(".gz")
    suffix = stem.rsplit("_", 1)[-1].lower()
    if telescope == "JWST" and suffix in _JWST_LEVELS:
        level = _JWST_LEVELS[suffix]
        if suffix == "i2d":
            association = re.match(r"^jw\d{5}-[oc]\d{3,4}_", stem)
            level = (
                "Stage 3: combined, resampled mosaic"
                if association
                else "Stage 2: resampled single exposure"
            )
        return level
    if telescope == "HST" and suffix in _HST_LEVELS:
        return _HST_LEVELS[suffix]
    return "unknown"


def _first(image: ImageProduct, *keys: str) -> Any:
    for key in keys:
        value = image.keyword(key)
        if value not in (None, ""):
            return value
    return None


def fact_sheet(image: ImageProduct) -> dict[str, Any]:
    """Collect metadata facts and pixel measurements of an image.

    Returns a JSON-serialisable dict with sections ``file``, ``observation``, ``calibration``,
    ``image``, ``measured`` and ``notes``.
    """
    name, ver = image.source.extension
    derived_from = image.primary_header.get("CUTSRC")
    band = image.bandpass
    sheet: dict[str, Any] = {
        "file": {
            "name": image.source.filename,
            "extension": f"{name},{ver}",
            "sha256": image.source.sha256,
            "derived_cutout_of": derived_from,
            "product_level": product_level(derived_from or image.source.filename, image.telescope)
            + (" (inferred from filename)" if derived_from is None else " (of source product)"),
        },
        "observation": {
            "telescope": image.telescope,
            "instrument": image.instrument,
            "detector": image.detector,
            "mode": _first(image, "EXP_TYPE", "OBSMODE"),
            "bandpass": band.key,
            "optical_elements": band.elements,
            "nominal_wavelength_um": (
                round(float(band.nominal_wavelength.to_value("um")), 4)
                if band.nominal_wavelength is not None
                else None
            ),
            "pivot_wavelength_um": (
                round(float(band.pivot.to_value("um")), 5) if band.pivot is not None else None
            ),
            "target_designation": _first(image, "TARGPROP", "TARGNAME", "OBJECT"),
            "program": _first(image, "PROGRAM", "PROPOSID"),
            "observation": _first(image, "OBSERVTN"),
            "date_obs": _first(image, "DATE-BEG", "DATE-OBS"),
            "exposure_time_s": _first(image, "EFFEXPTM", "XPOSURE", "EXPTIME"),
        },
        "calibration": {
            "pipeline_version": _first(image, "CAL_VER"),
            "reference_context": _first(image, "CRDS_CTX"),
            "pixel_area_sr": _first(image, "PIXAR_SR"),
        },
        "image": {
            "shape": list(image.data.shape),
            "unit": str(image.unit) if image.unit is not None else None,
            "has_uncertainty": image.uncertainty is not None,
            "masked_fraction": round(image.n_masked / image.data.size, 4),
        },
        "measured": {},
        "notes": list(image.notes) + [f"bandpass: {n}" for n in band.notes],
    }
    if image.wcs is not None:
        scales = proj_plane_pixel_scales(image.wcs.celestial) * 3600.0
        ny, nx = image.data.shape
        centre = image.wcs.pixel_to_world((nx - 1) / 2, (ny - 1) / 2)
        sheet["image"].update(
            {
                "pixel_scale_arcsec": [round(float(s), 5) for s in scales],
                "field_arcsec": [round(float(nx * scales[0]), 2), round(float(ny * scales[1]), 2)],
                "centre_icrs_deg": [
                    round(float(centre.icrs.ra.deg), 6),
                    round(float(centre.icrs.dec.deg), 6),
                ],
            }
        )
    good = (
        np.asarray(image.data, dtype=float)[~image.mask]
        if image.mask is not None
        else np.ravel(image.data)
    )
    good = good[np.isfinite(good)]
    if good.size:
        _, median, std = sigma_clipped_stats(good, sigma=3.0, maxiters=10)
        unit = str(image.unit) if image.unit is not None else "native units"
        sheet["measured"] = {
            "pixels_used": int(good.size),
            "sigma_clipped_median": float(median),
            "sigma_clipped_std": float(std),
            "unit": unit,
            "method": "3-sigma clipped statistics of unmasked finite pixels (includes sources)",
        }
        if image.uncertainty is not None:
            err = np.asarray(image.uncertainty.array, dtype=float)
            err = err[~image.mask] if image.mask is not None else err.ravel()
            err = err[np.isfinite(err)]
            if err.size:
                sheet["measured"]["median_err"] = float(np.median(err))
    return sheet


def format_fact_sheet(sheet: dict[str, Any]) -> str:
    """Human-readable text rendering of :func:`fact_sheet`."""
    labels = {
        "file": "File",
        "observation": "Observation (from metadata)",
        "calibration": "Calibration (from metadata)",
        "image": "Image",
        "measured": "Measured from pixels (L1)",
    }
    lines = []
    for section, title in labels.items():
        values = {k: v for k, v in sheet[section].items() if v not in (None, {}, [])}
        if not values:
            continue
        lines.append(title)
        for key, value in values.items():
            label = key.replace("_", " ")
            if key == "target_designation":
                label = "target designation *"
            if isinstance(value, float):
                value = f"{value:.6g}"
            lines.append(f"  {label:<28} {value}")
    if sheet["observation"].get("target_designation"):
        lines.append(
            "  * the observer's label for the pointing, not an identification of the image content"
        )
    routine = [n for n in sheet["notes"] if _ROUTINE_FIX.search(n)]
    other = [n for n in sheet["notes"] if n not in routine]
    if other or routine:
        lines.append("Notes")
        lines += [f"  - {n.splitlines()[0][:150]}" for n in other]
        if routine:
            lines.append(f"  - {len(routine)} routine astropy header normalisation(s) (see --json)")
    return "\n".join(lines)
