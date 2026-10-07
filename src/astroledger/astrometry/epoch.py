"""Observation epochs and proper-motion propagation of Gaia positions.

Gaia DR3 positions refer to ``ref_epoch`` (J2016.0, TCB). Comparing them with an image taken
years earlier or later needs each star moved along its proper motion; at 6 years, a star with
50 mas/yr moves 0.3″, several NIRCam pixels.

Propagation here is along the great circle defined by the proper-motion vector. Parallax and
radial velocity are ignored: over a few years their effect is below 0.1 mas for nearly all
Gaia stars, but annual parallax shifts of up to the parallax itself are not modelled.
"""

from __future__ import annotations

import numpy as np
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.table import QTable
from astropy.time import Time

from astroledger.core.product import ImageProduct

__all__ = ["observation_epoch", "propagate"]

# Header keywords giving the exposure mid-time (MJD), most specific first.
_MID_KEYWORDS = ("MJD-AVG", "EXPMID", "MJD-MID")


def observation_epoch(source: ImageProduct | fits.Header) -> tuple[Time, str]:
    """Mid-exposure time of an image, and the header keyword(s) it came from.

    JWST: ``MJD-AVG`` / ``EXPMID``. HST: the mean of ``EXPSTART`` and ``EXPEND``. Otherwise
    ``DATE-AVG``, then ``DATE-OBS`` (+ ``TIME-OBS``), which is the exposure *start*. All are UTC
    unless ``TIMESYS`` says otherwise.

    Raises
    ------
    KeyError
        If no usable time keyword is present.
    """
    headers = (
        [source.primary_header, source.header] if isinstance(source, ImageProduct) else [source]
    )
    headers = [h for h in headers if h is not None]

    def get(key):
        for header in headers:
            if key in header and header[key] not in (None, ""):
                return header[key]
        return None

    scale = str(get("TIMESYS") or "UTC").lower()
    scale = scale if scale in Time.SCALES else "utc"
    for key in _MID_KEYWORDS:
        value = get(key)
        if value is not None:
            return Time(float(value), format="mjd", scale=scale), key
    start, end = get("EXPSTART"), get("EXPEND")
    if start is not None and end is not None:
        return Time((float(start) + float(end)) / 2, format="mjd", scale=scale), "EXPSTART/EXPEND"
    if get("DATE-AVG") is not None:
        return Time(get("DATE-AVG"), scale=scale), "DATE-AVG"
    date = get("DATE-OBS")
    if date is not None:
        clock = get("TIME-OBS")
        text = f"{date}T{clock}" if clock and "T" not in str(date) else str(date)
        return Time(text, scale=scale), "DATE-OBS (exposure start)"
    raise KeyError("no observation time keyword (MJD-AVG, EXPMID, EXPSTART/EXPEND, DATE-OBS)")


def propagate(gaia: QTable, epoch: Time) -> QTable:
    """Gaia positions and their errors at ``epoch``.

    Adds columns ``ra_epoch``, ``dec_epoch`` (deg), ``ra_epoch_error`` (error of RA·cos Dec, mas),
    ``dec_epoch_error`` (mas) and ``pm_missing`` (True for two-parameter solutions, whose
    position is left at ``ref_epoch`` because their motion is unknown). Errors combine the
    reference-epoch error and the proper-motion error times the interval; the RA/proper-motion
    correlations are not available in the default columns and are ignored.

    Parameters
    ----------
    gaia : QTable
        With ``ra``, ``dec``, ``ra_error``, ``dec_error``, ``pmra``, ``pmdec``,
        ``pmra_error``, ``pmdec_error`` and ``ref_epoch`` (Julian year, TCB).
    epoch : astropy.time.Time
        Target epoch.
    """
    out = QTable(gaia, copy=True)
    ref_epoch = np.asarray(u.Quantity(out["ref_epoch"], u.yr).value, dtype=float)
    dt = (epoch.tcb.jyear - ref_epoch) * u.yr
    pmra = u.Quantity(out["pmra"], u.mas / u.yr)
    pmdec = u.Quantity(out["pmdec"], u.mas / u.yr)
    missing = ~np.isfinite(pmra) | ~np.isfinite(pmdec)
    pmra = np.where(missing, 0.0, pmra.value) * pmra.unit
    pmdec = np.where(missing, 0.0, pmdec.value) * pmdec.unit

    start = SkyCoord(u.Quantity(out["ra"], u.deg), u.Quantity(out["dec"], u.deg))
    shift = np.hypot(pmra, pmdec) * dt
    angle = np.arctan2(pmra, pmdec)  # position angle, east of north
    moved = start.directional_offset_by(angle, shift.to(u.deg))
    out["ra_epoch"] = moved.ra.to(u.deg)
    out["dec_epoch"] = moved.dec.to(u.deg)

    def grown(position_error, pm_error):
        pm_error = np.where(missing, 0.0, u.Quantity(pm_error, u.mas / u.yr).value)
        return np.hypot(u.Quantity(position_error, u.mas).value, pm_error * dt.value) * u.mas

    out["ra_epoch_error"] = grown(out["ra_error"], out["pmra_error"])
    out["dec_epoch_error"] = grown(out["dec_error"], out["pmdec_error"])
    out["pm_missing"] = missing
    out.meta["epoch"] = {
        "target_jyear_tcb": float(epoch.tcb.jyear),
        "target_iso_utc": epoch.utc.isot,
        "median_interval_yr": float(np.median(dt.value)) if len(dt) else None,
        "method": "great-circle proper-motion propagation; parallax and RV ignored",
    }
    return out
