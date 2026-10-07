"""Search MAST for JWST/HST observations and download their products.

Built on ``astroquery.mast.Observations`` (MAST's recommended Python interface). Search results
are normalised to a small, documented set of columns with the bandpass resolved from MAST's
``filters`` string, so NIRCam pupil-wheel filters and NIRISS ``CLEAR`` entries are not mislabelled.

Downloads keep archive filenames. When a JWST product is available in MAST's public AWS copy it
can be fetched from there (see :mod:`astroledger.archives.cloud`), with ETag verification.
"""

from __future__ import annotations

from pathlib import Path

from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.table import Table

from astroledger.core.bandpass import NIRCAM_PUPIL_FILTER_PAIRS
from astroledger.provenance import step

__all__ = ["SEARCH_COLUMNS", "bandpass_from_mast", "download", "products", "search"]

#: Columns returned by :func:`search` (subset of the MAST CAOM observation table).
SEARCH_COLUMNS = (
    "obs_id",
    "target_name",
    "proposal_id",
    "proposal_pi",
    "instrument_name",
    "filters",
    "bandpass",
    "t_exptime",
    "calib_level",
    "dataRights",
    "t_min",
    "s_ra",
    "s_dec",
    "obsid",
)
_CLEAR = {"CLEAR", "CLEARP", "OPAQUE"}


def bandpass_from_mast(instrument_name: str, filters: str) -> str | None:
    """Resolve the bandpass from MAST's ``instrument_name`` and ``filters`` columns.

    MAST lists optical elements separated by ``;`` (e.g. ``"F444W;F405N"``,
    ``"CLEAR;F150W"``). Rules match :class:`astroledger.core.Bandpass`: a NIRCam pupil-wheel
    filter wins over its filter-wheel partner; CLEAR positions are ignored. Returns None when
    the elements do not reduce to one bandpass.
    """
    instrument = (instrument_name or "").split("/")[0].upper()
    elements = [e.strip().upper() for e in (filters or "").split(";") if e.strip()]
    if instrument == "NIRCAM":
        pupil_filters = [e for e in elements if e in NIRCAM_PUPIL_FILTER_PAIRS]
        if len(pupil_filters) == 1:
            return pupil_filters[0]
    real = [e for e in elements if e not in _CLEAR]
    return real[0] if len(real) == 1 else None


def _observations():
    from astroquery.mast import Observations

    return Observations


def search(
    target: str | SkyCoord | None = None,
    *,
    radius: u.Quantity = 3 * u.arcmin,
    collection: str = "JWST",
    instrument: str | None = None,
    calib_level: int | list[int] = 3,
    proposal_id: str | None = None,
    dataproduct_type: str = "image",
) -> Table:
    """Search MAST observations.

    Parameters
    ----------
    target : str or SkyCoord, optional
        Object name (resolved by MAST) or coordinates.
    radius : Quantity
        Cone radius around ``target``.
    collection : str
        ``"JWST"``, ``"HST"``, ...
    instrument : str, optional
        MAST ``instrument_name``, e.g. ``"NIRCAM/IMAGE"``, ``"MIRI/IMAGE"``, ``"ACS/WFC"``.
    calib_level : int or list of int
        3 for combined products (default); 2 for per-exposure calibrated files.
    proposal_id : str, optional
        Program number, e.g. ``"2733"``.

    Returns
    -------
    astropy.table.Table
        Columns :data:`SEARCH_COLUMNS`, one row per observation.
    """
    criteria: dict = {
        "obs_collection": collection,
        "calib_level": calib_level,
        "dataproduct_type": dataproduct_type,
    }
    if instrument:
        criteria["instrument_name"] = instrument
    if proposal_id:
        criteria["proposal_id"] = str(proposal_id)
    if isinstance(target, SkyCoord):
        criteria["coordinates"] = target
        criteria["radius"] = radius
    elif target:
        criteria["objectname"] = target
        criteria["radius"] = radius
    table = _observations().query_criteria(**criteria)
    table["bandpass"] = [
        bandpass_from_mast(str(i), str(f)) or ""
        for i, f in zip(table["instrument_name"], table["filters"], strict=True)
    ]
    return table[[c for c in SEARCH_COLUMNS if c in table.colnames]]


def products(observations: Table, *, suffixes: tuple[str, ...] = ("I2D", "CAT")) -> Table:
    """Science products of observations, filtered by product type.

    ``suffixes`` are MAST ``productSubGroupDescription`` values, e.g. ``"I2D"`` (combined image),
    ``"CAT"`` (source catalogue), ``"CAL"`` (calibrated exposure), ``"DRZ"``/``"DRC"`` (HST).
    """
    table = _observations().get_product_list(observations)
    keep = [str(s).upper() in suffixes for s in table["productSubGroupDescription"]]
    return table[keep]


@step("archives.mast.download", version="1")
def download(product_table: Table, dest_dir: str | Path) -> list[Path]:
    """Download products with astroquery, keeping archive filenames. Returns local paths."""
    manifest = _observations().download_products(product_table, download_dir=str(dest_dir))
    failed = [str(r["Local Path"]) for r in manifest if r["Status"] != "COMPLETE"]
    if failed:
        raise OSError(f"downloads not complete: {failed}")
    return [Path(p) for p in manifest["Local Path"]]
