"""Builders for small synthetic FITS files that mimic real JWST, HST and camera product layouts.

They reproduce the *structure* of archive products (extension names, versions, header keywords,
units, data-quality conventions), not their science content. Pixel values are seeded noise.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from astropy.io import fits

SHAPE = (64, 80)  # (ny, nx); non-square to catch axis-order mistakes


def tan_wcs(crval: tuple[float, float], scale_arcsec: float, shape=SHAPE) -> dict:
    """Celestial TAN WCS keywords centred on the image."""
    ny, nx = shape
    deg = scale_arcsec / 3600.0
    return {
        "CTYPE1": "RA---TAN",
        "CTYPE2": "DEC--TAN",
        "CUNIT1": "deg",
        "CUNIT2": "deg",
        "CRVAL1": crval[0],
        "CRVAL2": crval[1],
        "CRPIX1": (nx + 1) / 2,
        "CRPIX2": (ny + 1) / 2,
        "CD1_1": -deg,
        "CD1_2": 0.0,
        "CD2_1": 0.0,
        "CD2_2": deg,
    }


def sip(order: int = 2) -> dict:
    """SIP distortion keywords (tiny coefficients), as in JWST Stage-2 FITS WCS approximations."""
    cards = {"CTYPE1": "RA---TAN-SIP", "CTYPE2": "DEC--TAN-SIP", "A_ORDER": order, "B_ORDER": order}
    cards.update({"A_2_0": 1e-7, "B_0_2": 1e-7})
    return cards


def _noise(seed: int, shape=SHAPE, dtype="float32") -> np.ndarray:
    return np.random.default_rng(seed).normal(1.0, 0.1, shape).astype(dtype)


def _primary(**cards) -> fits.PrimaryHDU:
    hdu = fits.PrimaryHDU()
    hdu.header.update(cards)
    return hdu


def _image(data, name, ver=1, **cards) -> fits.ImageHDU:
    hdu = fits.ImageHDU(data, name=name, ver=ver)
    hdu.header.update(cards)
    return hdu


def jwst_cal(path: Path) -> Path:
    """JWST Stage-2 ``_cal``: SCI (MJy/sr, NaN where flagged), ERR, DQ (uint32), ASDF table."""
    sci = _noise(1)
    sci[10:12, 20:22] = np.nan  # pipeline sets DO_NOT_USE pixels to NaN
    dq = np.zeros(SHAPE, "uint32")
    dq[10:12, 20:22] = 1  # DO_NOT_USE
    dq[30, 40] = 1  # DO_NOT_USE on a finite pixel
    dq[5, 5] = 2  # SATURATED only (informational): must stay unmasked
    fits.HDUList(
        [
            _primary(
                TELESCOP="JWST",
                INSTRUME="NIRCAM",
                DETECTOR="NRCA1",
                FILTER="F200W",
                PUPIL="CLEAR",
                EXP_TYPE="NRC_IMAGE",
                CAL_VER="3.0.0",
                CRDS_CTX="jwst_1581.pmap",
            ),
            _image(sci, "SCI", BUNIT="MJy/sr", **{**tan_wcs((202.47, 47.20), 0.031), **sip()}),
            _image(np.full(SHAPE, 0.1, "float32"), "ERR", BUNIT="MJy/sr"),
            _image(dq, "DQ"),
            fits.BinTableHDU.from_columns(
                [fits.Column(name="ASDF_METADATA", format="1B", array=np.zeros(1, "uint8"))],
                name="ASDF",
            ),
        ]
    ).writeto(path)
    return path


def jwst_i2d(path: Path) -> Path:
    """JWST Stage-3 ``_i2d``: SCI (plain TAN, no SIP), ERR, CON (3-D), WHT, ASDF; no DQ.

    NaN marks pixels without coverage.
    """
    sci = _noise(2)
    sci[:, :5] = np.nan
    fits.HDUList(
        [
            _primary(TELESCOP="JWST", INSTRUME="NIRCAM", DETECTOR="MULTIPLE", FILTER="F444W"),
            _image(sci, "SCI", BUNIT="MJy/sr", **tan_wcs((10.0, -30.0), 0.063)),
            _image(np.full(SHAPE, 0.05, "float32"), "ERR", BUNIT="MJy/sr"),
            _image(np.ones((1, *SHAPE), "int32"), "CON"),
            _image(np.ones(SHAPE, "float32"), "WHT"),
            fits.BinTableHDU.from_columns(
                [fits.Column(name="ASDF_METADATA", format="1B", array=np.zeros(1, "uint8"))],
                name="ASDF",
            ),
        ]
    ).writeto(path)
    return path


def jwst_rate(path: Path) -> Path:
    """JWST Stage-1 ``_rate``: DN/s, no celestial WCS."""
    fits.HDUList(
        [
            _primary(
                TELESCOP="JWST", INSTRUME="NIRISS", DETECTOR="NIS", FILTER="CLEAR", PUPIL="F150W"
            ),
            _image(_noise(3), "SCI", BUNIT="DN/s"),
            _image(np.full(SHAPE, 0.2, "float32"), "ERR", BUNIT="DN/s"),
            _image(np.zeros(SHAPE, "uint32"), "DQ"),
        ]
    ).writeto(path)
    return path


def jwst_uncal(path: Path) -> Path:
    """JWST Stage-0 ``_uncal``: 4-D ramps (nints, ngroups, ny, nx)."""
    fits.HDUList(
        [
            _primary(TELESCOP="JWST", INSTRUME="NIRCAM", DETECTOR="NRCA1"),
            _image(np.zeros((1, 3, *SHAPE), "uint16"), "SCI", BUNIT="DN"),
        ]
    ).writeto(path)
    return path


def hst_flt_two_chip(path: Path) -> Path:
    """HST ACS/WFC ``_flt``: SCI/ERR/DQ for chips EXTVER 1 and 2, BUNIT 'ELECTRONS', int16 DQ."""
    hdus = [_primary(TELESCOP="HST", INSTRUME="ACS", DETECTOR="WFC", FILTER1="F606W")]
    for ver, (crval, seed) in enumerate((((150.10, 2.20), 4), ((150.10, 2.25), 5)), start=1):
        dq = np.zeros(SHAPE, "int16")
        dq[3, 4 + ver] = 4096  # e.g. a cosmic-ray flag
        hdus += [
            _image(
                _noise(seed), "SCI", ver, BUNIT="ELECTRONS", CCDCHIP=3 - ver, **tan_wcs(crval, 0.05)
            ),
            _image(np.full(SHAPE, 5.0, "float32"), "ERR", ver, BUNIT="ELECTRONS"),
            _image(dq, "DQ", ver),
        ]
    fits.HDUList(hdus).writeto(path)
    return path


def hst_drz(path: Path) -> Path:
    """HST drizzled ``_drz``: SCI in ELECTRONS/S with WHT and CTX; no ERR or DQ."""
    fits.HDUList(
        [
            _primary(TELESCOP="HST", INSTRUME="WFC3", DETECTOR="UVIS"),
            _image(_noise(6), "SCI", BUNIT="ELECTRONS/S", **tan_wcs((83.82, -5.39), 0.04)),
            _image(np.ones(SHAPE, "float32"), "WHT"),
            _image(np.ones(SHAPE, "int32"), "CTX"),
        ]
    ).writeto(path)
    return path


def camera_frame(path: Path, *, bunit: str | None = "ADU") -> Path:
    """Single-HDU frame from an amateur camera: uint16 in the primary HDU, no WCS."""
    hdu = fits.PrimaryHDU(np.random.default_rng(7).integers(900, 1100, SHAPE).astype("uint16"))
    hdu.header.update(INSTRUME="Generic CMOS", EXPTIME=60.0)
    if bunit is not None:
        hdu.header["BUNIT"] = bunit
    hdu.writeto(path)
    return path


def two_unnamed_images(path: Path) -> Path:
    """No SCI extension and two image HDUs: genuinely ambiguous."""
    fits.HDUList([fits.PrimaryHDU(_noise(8)), fits.ImageHDU(_noise(9))]).writeto(path)
    return path
